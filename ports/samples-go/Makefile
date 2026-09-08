# Every port exposes setup / test / clean. scripts/run-port.sh calls setup then
# test, and CI calls exactly that, so a port that runs locally runs in CI.

.PHONY: setup test clean

setup: ## install this port's dependencies
	@echo "samples-go: no dependencies yet (cases are Go tests driving the HTTP API)"

# Exits 0 with ZERO cases, deliberately, and says so loudly.
#
# CI discovers ports from the directory listing (.github/workflows), so a
# scaffold that exits 1 breaks the pipeline for every other port. Exiting 0
# while reporting nothing would be worse in the other direction -- a port that
# reads as passing while covering nothing is the exact failure ports/README.md
# spent two days claiming about dbos-transact-py.
#
# So: succeed, and print the count. When the first case lands, this target runs
# it and the count stops being zero.
test: ## run this port against the cleat toolchain on PATH
	@echo "samples-go: 0 cases ported. Scaffolded 2026-09-07; see README.md for the"
	@echo "            priority order. This target passes because there is nothing"
	@echo "            to run, NOT because anything was verified."

clean: ## remove build artifacts
	@rm -rf out
