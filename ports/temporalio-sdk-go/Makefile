# Every port exposes setup / test / clean. scripts/run-port.sh calls setup then
# test, and CI calls exactly that, so a port that runs locally runs in CI.

.PHONY: setup test clean

setup: ## install this port's dependencies
	@# Nothing to install: the test module is stdlib-only (see go.mod) and
	@# these cases deploy no WASM.
	@go version

test: ## run this port against the cleat toolchain on PATH
	@# -count=1 defeats the test cache. These tests write rows to a live
	@# database; a cached PASS from an earlier toolchain would be reported as
	@# a result for this one.
	@# -p 1 and no t.Parallel(): every case here writes to workflow_schedules
	@# under a name it chose, and the worker is one process shared by every
	@# port in a run.
	go test ./tests/ -v -count=1 -p 1 -timeout 5m

clean: ## remove build artifacts
	@rm -rf out
