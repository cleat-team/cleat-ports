# Every port exposes setup / test / clean. scripts/run-port.sh calls setup then
# test, and CI calls exactly that, so a port that runs locally runs in CI.

.PHONY: setup test clean

setup: ## install this port's dependencies
	@# Nothing to install. The test module is stdlib-only (see go.mod), and the
	@# workflow package gets its dependencies from the cleat checkout that
	@# scripts/build-workflow.sh stages it into.
	@go version

test: ## run this port against the cleat toolchain on PATH
	@# -count=1 defeats the test cache. These tests deploy WASM to a live
	@# database and start runs on it; a cached PASS from an earlier toolchain
	@# would be reported as a result for this one.
	@# -p 1 and no t.Parallel(): every case here writes to workflow_schedules or
	@# idempotency_keys under a name it chose, and the WORKER is one process
	@# shared by every port in a run -- "is the winner still unfinished" is not
	@# a question to answer while another port is filling the same queue.
	@# 15m rather than 5m: the first duplicate-start case compiles a workflow to
	@# WASM, which dominates this port's wall clock.
	go test ./tests/ -v -count=1 -p 1 -timeout 15m

clean: ## remove build artifacts
	@rm -rf out
