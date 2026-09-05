# Every port exposes setup / test / clean. scripts/run-port.sh calls setup then
# test, and CI calls exactly that, so a port that runs locally runs in CI.

.PHONY: setup test clean

setup: ## install this port's dependencies
	@echo "TODO: install dependencies for this port"

test: ## run this port against the cleat toolchain on PATH
	@echo "TODO: run this port's tests"; exit 1

clean: ## remove build artifacts
	@rm -rf .venv __pycache__ .pytest_cache out
