VENV := .venv
PY   := $(VENV)/bin/python

# Bare `python3` is 3.9.6 on current macOS and cleat-sdk requires >=3.10, so
# `make setup` died on `pip install -e` with "requires a different Python".
# CI never saw it: actions/setup-python pins 3.12 there, so the one environment
# where this breaks is the contributor laptop this repo is meant to be run on.
# Pick the newest interpreter that satisfies the SDK rather than trusting the
# name `python3` to mean anything in particular.
PYTHON ?= $(shell for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do \
	command -v $$p >/dev/null 2>&1 && \
	$$p -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null && \
	{ echo $$p; break; }; \
	done)

.PHONY: setup test clean

setup: ## create the venv and install cleat's Python SDK
	@test -n "$(PYTHON)" || { \
		echo "no Python >= 3.10 found; cleat-sdk requires it" >&2; \
		echo "default python3 is $$(python3 -V 2>&1)" >&2; \
		echo "install one, e.g. brew install python@3.12, then re-run" >&2; \
		exit 2; }
	@echo "==> using $(PYTHON) ($$($(PYTHON) -V 2>&1))"
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet pytest
	# The Python SDK ships from the cleat repo cloned by scripts/install-cleat.sh,
	# so the port always tests the SDK matching the toolchain under test rather
	# than the last version published to PyPI.
	$(PY) -m pip install --quiet -e ../../.cleat-src/python-sdk

test: ## run the ported tests
	$(PY) -m pytest -v tests/

clean:
	rm -rf $(VENV) __pycache__ tests/__pycache__ .pytest_cache
