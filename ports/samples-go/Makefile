# Every port exposes setup / test / clean. scripts/run-port.sh calls setup then
# test, and CI calls exactly that, so a port that runs locally runs in CI.

.PHONY: setup test clean

setup: ## install this port's dependencies
	@# Nothing to install. The test module is stdlib-only on purpose (see
	@# go.mod), and the workflow packages get their dependencies from the
	@# cleat checkout that scripts/build-workflow.sh stages them into.
	@go version

test: ## run this port against the cleat toolchain on PATH
	@# -count=1 defeats the test cache. These tests deploy WASM to a live
	@# database and read a service's call log; a cached PASS from an earlier
	@# toolchain would be reported as a result for this one.
	@# -p 1 and no t.Parallel(): the fixture's call log is shared state keyed
	@# per test, but the WORKER is one process shared by every port in a run,
	@# and "did compensation run" is not a question you want to answer while
	@# another test is filling the same worker's queue.
	go test ./tests/ -v -count=1 -p 1 -timeout 15m

clean: ## remove build artifacts
	@rm -rf out
