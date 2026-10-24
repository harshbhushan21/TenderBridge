"""Turnover and net-worth eligibility checks (deterministic)."""
from __future__ import annotations

from backend.app.ops.langsmith import traceable
from backend.app.schemas.eligibility import (
    Calculation,
    CompanyProfile,
    EligibilityStatus,
    FinancialRecord,
    NetWorthRule,
    RuleResult,
    TurnoverRule,
)
from backend.app.tools.date_normalization import fiscal_year_key, format_inr


def _select_years(financials: list[FinancialRecord], fiscal_years: list[str],
                  n_years: int) -> tuple[list[FinancialRecord], list[str]]:
    by_key = {fiscal_year_key(f.fiscal_year): f for f in financials}
    missing: list[str] = []
    if fiscal_years:
        chosen = []
        for fy in fiscal_years:
            k = fiscal_year_key(fy)
            if k in by_key:
                chosen.append(by_key[k])
            else:
                missing.append(fy)
        return chosen, missing
    keys = sorted(by_key)[-n_years:] if n_years > 0 else sorted(by_key)
    chosen = [by_key[k] for k in keys]
    if len(chosen) < n_years:
        missing.append(f"{n_years - len(chosen)} fiscal year(s) of financials")
    return chosen, missing


@traceable(name="check_turnover", run_type="tool")
def check_turnover(financials: list[FinancialRecord], rule: TurnoverRule,
                   company: CompanyProfile | None) -> RuleResult:
    years, missing = _select_years(financials, rule.fiscal_years, rule.n_years)
    calcs: list[Calculation] = []
    evidence = [f.source for f in years if f.source]
    unknowns = list(missing)

    is_mse = bool(company and company.is_mse)
    mse_applies = bool(rule.mse_relaxation_allowed and is_mse and rule.mse_threshold_inr)
    threshold = rule.mse_threshold_inr if mse_applies else rule.general_threshold_inr
    if threshold is None:
        raise ValueError("turnover rule must define a general threshold")
    calcs.append(Calculation(label="general threshold", value=format_inr(rule.general_threshold_inr)))
    if rule.mse_threshold_inr:
        calcs.append(Calculation(label="MSE relaxed threshold",
                                 value=format_inr(rule.mse_threshold_inr)))
    calcs.append(Calculation(label="bidder is MSE (Udyam)", value=is_mse))
    calcs.append(Calculation(label="MSE relaxation allowed by tender", value=rule.mse_relaxation_allowed))
    calcs.append(Calculation(label="applicable threshold", value=format_inr(threshold)))

    if not years:
        return RuleResult(rule_kind="turnover", status=EligibilityStatus.needs_human,
                          summary="No financial records available to evaluate turnover.",
                          calculations=calcs, unknowns=unknowns or ["financials"],
                          needs_human_reason="missing financial records")

    for f in years:
        calcs.append(Calculation(label=f"revenue {f.fiscal_year}", value=format_inr(f.revenue_inr)))
    revenues = [f.revenue_inr for f in years]
    if rule.aggregation == "average":
        actual = sum(revenues) / len(revenues)
        passed = actual >= threshold
        calcs.append(Calculation(label=f"average of {len(revenues)} FYs", value=format_inr(actual)))
    elif rule.aggregation == "sum":
        actual = sum(revenues)
        passed = actual >= threshold
        calcs.append(Calculation(label="sum", value=format_inr(actual)))
    elif rule.aggregation == "each_year":
        actual = min(revenues)
        passed = actual >= threshold
        calcs.append(Calculation(label="minimum year", value=format_inr(actual)))
    else:  # any_year
        actual = max(revenues)
        passed = actual >= threshold
        calcs.append(Calculation(label="best year", value=format_inr(actual)))

    basis = "MSE relaxed" if mse_applies else "general"
    actions: list[str] = []
    if passed and mse_applies:
        actions.append("Attach valid Udyam/MSE certificate to claim turnover relaxation")
    if passed and any(not f.ca_certified for f in years):
        actions.append("Obtain CA-certified turnover statement for all evaluated years")

    if missing:
        status = EligibilityStatus.needs_human if not passed else EligibilityStatus.partial
        summary = f"Turnover evaluated on incomplete data ({', '.join(missing)} missing)."
    elif passed:
        status = EligibilityStatus.meets
        summary = (f"{rule.aggregation.replace('_', ' ')} turnover {format_inr(actual)} meets the "
                   f"{basis} threshold of {format_inr(threshold)}.")
        if mse_applies and actual < rule.general_threshold_inr:
            summary += f" (Would fail the general threshold of {format_inr(rule.general_threshold_inr)}.)"
    else:
        status = EligibilityStatus.gap
        summary = (f"{rule.aggregation.replace('_', ' ')} turnover {format_inr(actual)} is below the "
                   f"{basis} threshold of {format_inr(threshold)}.")
        if rule.mse_threshold_inr and not mse_applies:
            reason = "tender does not allow MSE relaxation" if not rule.mse_relaxation_allowed \
                else "bidder is not a registered MSE"
            summary += f" MSE relaxation not applied: {reason}."
    return RuleResult(rule_kind="turnover", status=status, summary=summary, calculations=calcs,
                      evidence=evidence, actions=actions, unknowns=unknowns)


@traceable(name="check_net_worth", run_type="tool")
def check_net_worth(financials: list[FinancialRecord], rule: NetWorthRule) -> RuleResult:
    years, missing = _select_years(financials, rule.fiscal_years, rule.n_years)
    calcs: list[Calculation] = []
    evidence = [f.source for f in years if f.source]
    unknown_years = [f.fiscal_year for f in years if f.net_worth_inr is None]
    if not years or unknown_years:
        return RuleResult(rule_kind="net_worth", status=EligibilityStatus.needs_human,
                          summary="Net worth not available for all evaluated years.",
                          evidence=evidence, unknowns=missing + unknown_years,
                          needs_human_reason="missing net worth")
    failures = []
    for f in years:
        nw = f.net_worth_inr or 0.0
        calcs.append(Calculation(label=f"net worth {f.fiscal_year}", value=format_inr(nw)))
        if (rule.strictly_positive and nw <= 0) or nw < rule.min_inr:
            failures.append(f.fiscal_year)
    if failures:
        return RuleResult(rule_kind="net_worth", status=EligibilityStatus.gap,
                          summary=f"Net worth requirement not met in {', '.join(failures)}.",
                          calculations=calcs, evidence=evidence, unknowns=missing)
    req = "positive" if rule.strictly_positive and rule.min_inr <= 0 else f"≥ {format_inr(rule.min_inr)}"
    return RuleResult(rule_kind="net_worth",
                      status=EligibilityStatus.meets if not missing else EligibilityStatus.partial,
                      summary=f"Net worth is {req} in all evaluated years.",
                      calculations=calcs, evidence=evidence, unknowns=missing)
