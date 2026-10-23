"""Date, datetime, money and fiscal-year normalisation (no LLM arithmetic)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from backend.app.schemas.requirements import Money

IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?([A-Za-z]{3,9})\.?,?[\s\-]+(\d{4})\b", re.I)
_TEXT_DATE_US = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
_TIME = re.compile(
    r"\b(\d{1,2})[:.](\d{2})\s*(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|hrs?|hours|ist)?\b", re.I)
_TIME_HRS = re.compile(r"\b(\d{2})(\d{2})\s*hrs\b", re.I)


def _mk_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str | date | datetime | None) -> date | None:
    """Parse Indian-style dates (day first). Returns None when unparseable — never guesses."""
    if text is None:
        return None
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    s = str(text).strip()
    if not s:
        return None
    m = _ISO_DATE.search(s)
    if m:
        return _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _NUMERIC_DATE.search(s)
    if m:
        return _mk_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = _TEXT_DATE.search(s)
    if m and m.group(2).lower() in _MONTHS:
        return _mk_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = _TEXT_DATE_US.search(s)
    if m and m.group(1).lower() in _MONTHS:
        return _mk_date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def parse_datetime(text: str | datetime | date | None, *, default_hour: int | None = None) -> datetime | None:
    """Parse a date plus optional time (IST assumed). Without a time, uses default_hour or 00:00."""
    if text is None:
        return None
    if isinstance(text, datetime):
        return text if text.tzinfo else text.replace(tzinfo=IST)
    d = parse_date(text)
    if d is None:
        return None
    s = str(text)
    hour, minute = (default_hour or 0), 0
    # remove the date fragment so its digits are not mistaken for time
    stripped = _NUMERIC_DATE.sub(" ", _ISO_DATE.sub(" ", s))
    tm = _TIME.search(stripped)
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))
        suffix = (tm.group(4) or "").lower().replace(".", "")
        if suffix == "pm" and hour < 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0
    else:
        th = _TIME_HRS.search(stripped)
        if th:
            hour, minute = int(th.group(1)), int(th.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        hour, minute = 0, 0
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=IST)


# --------------------------------------------------------------------------- #
# Money                                                                        #
# --------------------------------------------------------------------------- #
_UNIT_FACTORS = {
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "cr.": 1e7, "crs": 1e7,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "lkh": 1e5,
    "million": 1e6, "mn": 1e6, "m": 1e6,
    "billion": 1e9, "bn": 1e9,
    "thousand": 1e3, "k": 1e3,
    "": 1.0, "inr": 1.0, "rs": 1.0, "rupees": 1.0,
}

_MONEY = re.compile(
    r"(?P<cur>₹|rs\.?|inr|rupees)?\s*(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>crores?|crs?\.?|lakhs?|lacs?|lkh|million|mn|billion|bn|thousand|l\b|k\b)?",
    re.I,
)


def to_inr(value: float | int | str, unit: str | None = None) -> float:
    """Convert a value in the given unit (crore, lakh, ...) to rupees."""
    if isinstance(value, str):
        value = float(value.replace(",", "").strip())
    u = (unit or "").strip().lower().rstrip(".")
    if u not in _UNIT_FACTORS:
        u = u.rstrip("s")
    factor = _UNIT_FACTORS.get(u)
    if factor is None:
        raise ValueError(f"unknown money unit '{unit}'")
    return float(value) * factor


def parse_money(text: str | None) -> Money | None:
    """Parse the first monetary amount in text. Requires a currency marker or a unit so
    that plain numbers (e.g. clause numbers) are not mistaken for money."""
    if not text:
        return None
    for m in _MONEY.finditer(str(text)):
        cur, unit = m.group("cur"), (m.group("unit") or "")
        if not cur and not unit:
            continue
        num = float(m.group("num").replace(",", ""))
        try:
            inr = to_inr(num, unit)
        except ValueError:
            continue
        return Money(amount_inr=inr, display=m.group(0).strip())
    return None


def parse_all_money(text: str | None) -> list[Money]:
    out: list[Money] = []
    if not text:
        return out
    for m in _MONEY.finditer(str(text)):
        cur, unit = m.group("cur"), (m.group("unit") or "")
        if not cur and not unit:
            continue
        try:
            out.append(Money(amount_inr=to_inr(float(m.group("num").replace(",", "")), unit),
                             display=m.group(0).strip()))
        except ValueError:
            continue
    return out


def format_inr(inr: float | None, unit: str = "crore") -> str:
    if inr is None:
        return "unknown"
    if unit == "lakh":
        return f"₹{inr / 1e5:,.2f} lakh"
    if unit == "rupees":
        return f"₹{inr:,.0f}"
    return f"₹{inr / 1e7:,.2f} Cr"


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", re.I)


def parse_percent(text: str | None) -> float | None:
    if not text:
        return None
    m = _PERCENT.search(str(text))
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Fiscal years / durations                                                     #
# --------------------------------------------------------------------------- #
_FY = re.compile(r"(?:FY\s*)?(\d{2,4})\s*[-/–]\s*(\d{2,4})", re.I)
_FY_SINGLE = re.compile(r"FY\s*'?(\d{2,4})", re.I)


def fiscal_year_key(label: str) -> int:
    """Return the ending calendar year of an Indian FY label: 'FY2023-24' -> 2024, 'FY24' -> 2024."""
    s = str(label).strip()
    m = _FY.search(s)
    if m:
        end = int(m.group(2))
        start = int(m.group(1))
        if end < 100:
            start_full = start if start >= 100 else 2000 + start
            end = (start_full // 100) * 100 + end
            if end < start_full:
                end += 100
        return end
    m = _FY_SINGLE.search(s)
    if m:
        y = int(m.group(1))
        return y + 2000 if y < 100 else y
    m = re.search(r"\d{4}", s)
    if m:
        return int(m.group(0))
    raise ValueError(f"cannot parse fiscal year '{label}'")


def fiscal_year_label(end_year: int) -> str:
    return f"FY{end_year - 1}-{str(end_year)[-2:]}"


def years_between(a: date, b: date) -> float:
    """Signed years from a to b (b - a)."""
    return (b - a).days / 365.25


def subtract_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - years, day=28)


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "single": 1, "a": 1, "an": 1,
}


def word_to_int(tok: str) -> int | None:
    tok = tok.strip().lower().strip("()")
    if tok.isdigit():
        return int(tok)
    return _NUMBER_WORDS.get(tok)
