VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: setup test clean

setup: ## create the venv and install cleat's Python SDK
	python3 -m venv $(VENV)
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
