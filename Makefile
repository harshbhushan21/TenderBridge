# Convenience wrapper for macOS/Linux. Every target runs dev.py, which also
# works on Windows: `uv run python dev.py <target>`.

TARGETS := help setup env doctor init-db migrate seed ingest-kb demo-cli evals reembed api web web-check demo reset-db test test-pg lint typecheck db-up db-down db-psql

.PHONY: $(TARGETS)

$(TARGETS):
	@uv run python dev.py $@
