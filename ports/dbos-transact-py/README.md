# dbos-transact-py

Port of [DBOS Transact (Python)](https://github.com/dbos-inc/dbos-transact-py)'s
test suite onto cleat's Python SDK. See [`UPSTREAM`](UPSTREAM) for the pinned
upstream commit.

## Why this upstream first

DBOS is the closest architectural match to cleat in the ecosystem: durable
execution backed by your own PostgreSQL, with no separate stateful service. Its
tests therefore assert the things cleat's design actually stakes out — queue
concurrency limits, recovery counts after a crash, deduplication and idempotency,
cron scheduling, schema migration — rather than the behaviour of a workflow
service cleat does not have.

It is also MIT licensed, which makes it portable here without friction, and
Python is a tier-1 language in cleat's `tiers.yaml`, so failures land on ground
cleat claims to hold rather than on a known gap.

## Upstream test inventory

Counts are `def test_*` in the pinned upstream commit. Priority reflects how much
each file says about an *engine* as opposed to an application or a web framework.

| Upstream file | Cases | Priority | Ported |
|---|---:|---|---:|
| `tests/test_queue.py` | 103 | **1** — concurrency limits, rate limits, dedup, priority | 6 |
| `tests/test_failures.py` | 43 | **1** — retries, error classification, recovery | 5 |
| `tests/test_workflow_management.py` | 44 | **1** — cancel, resume, fork, list, restart | 7 |
| `tests/test_concurrency.py` | 21 | **1** — concurrent execution and isolation | 4 |
| `tests/test_dbos.py` | 138 | 2 — broad core surface, mixed with SDK ergonomics | 12 |
| `tests/test_async.py` | 57 | 2 — async workflow and step semantics | 0 |
| `tests/test_scheduler.py` | 35 | 2 — cron and scheduled workflows | 0 |
| `tests/test_client.py` | 54 | 3 — client API surface, largely DBOS-specific | 0 |
| **Total in scope** | **495** | | **34** |

## What this port deliberately skips, and why

- `test_fastapi.py`, `test_flask.py`, `test_sqlalchemy.py` — web/ORM integration.
  Tests DBOS's framework adapters, not durable execution.
- `test_kafka.py` — DBOS's Kafka integration; cleat has no equivalent surface.
- `test_config.py`, `test_package.py`, `test_application_name.py`,
  `test_docker_secrets.py` — DBOS configuration and packaging.
- `test_croniter.py` — exercises the upstream's cron *library*, not the engine.
  The scheduling semantics worth porting live in `test_scheduler.py`.
- `test_cockroachdb.py`, `test_pgsql_client.py` — upstream-specific backends.
- `test_conductor_lifecycle.py`, `test_telemetry.py`, `test_admin_server.py` —
  DBOS Conductor and its observability stack.

## Status

**34 ported, 31 passing, 3 skipped.** The inventory above is the work plan; the
`Ported` column is the progress metric. Priority 1 first, and all four priority-1
files are now started.

The `Ported` column counts cases in *this* suite that carry an upstream
assertion, mapped to the upstream file the assertion came from:

| This suite | Cases | Mapped to |
|---|---:|---|
| `test_concurrency.py` | 4 | `test_queue.py` — concurrency keys are cleat's dedup surface |
| `test_retries.py` | 4 | `test_failures.py` |
| `test_recovery.py` | 1 | `test_failures.py` — recovery counts after a crash |
| `test_cancellation.py` | 4 | `test_workflow_management.py` |
| `test_detached.py` | 3 | `test_workflow_management.py` — the nearest thing cleat has to fork |
| `test_children.py` | 4 | `test_concurrency.py` — concurrent execution and isolation |
| `test_replay.py` | 2 | `test_dbos.py` |
| `test_send.py` | 2 | `test_dbos.py` — `send` delivery semantics |
| `test_promises.py` | 3 | `test_dbos.py` — `set_event`/`get_event` |
| `test_signals.py` | 1 | `test_dbos.py` — `recv` with a timeout |
| `test_determinism.py` | 4 | `test_dbos.py` — stable IDs and randomness under recovery |
| `test_locks.py` | 2 | `test_queue.py` — serialising work through a held key | It is not a
percentage of upstream: many upstream cases test the DBOS decorator API rather
than an engine property, and those have nothing to port.

The three skips are not unfinished work. Each is a cleat gap this port found,
left visible in the suite with the reason attached rather than deleted, so the
assertion a reader expects is where they expect it:

| Skipped | Gap |
|---|---|
| `test_blocked_task_runs_after_the_holder_finishes` | no queueing concurrency limit; a blocked start is rejected rather than deferred |
| `test_a_detached_run_can_be_addressed_by_its_caller` | `RunDetached` returns no handle |
| `test_cancel_stops_a_workflow_that_does_not_cooperate` | no pre-emptive cancellation and no cancelled terminal state |

### What the port has found so far

Every defect below was reachable only by running a compiled workflow against a
real database. None was visible from reading cleat's source, and cleat's own
suite was green throughout.

| cleat issue | Defect |
|---|---|
| #776 / #804 | the durable clock stopped for the length of every sleep, and a replay read a different clock than the original execution |
| #799 / #806 | `DurableSend`, `ResolvePromise` and `RejectPromise` were unreachable from a Go workflow |
| #771 / #808 | `cleat build` dropped a project's own SDK replace and compiled against the module proxy |
| #811 | replay never advanced the checksum chain, so any workflow recording an event after resuming died with a checksum mismatch |
| #812 | the worker never wired the promise store, so every await hung forever and `workflow_promises` had never held a row |
| #824 | a single-string entry point silently receives the raw input JSON, and the failure names whatever the argument was later used for |
| #813 | a promise was keyed by its creator, so no other workflow could settle one — which is the only thing a promise is for |
| #814 | a promise await re-armed its deadline every wake, so its timeout never fired — generation 3130 for a 5s timeout, now 2 |
| #775, #777, #787, #796 | earlier findings from the same harness |

## Running

```bash
make -C ../.. deps
make -C ../.. install-cleat
make -C ../.. port PORT=dbos-transact-py
```

## Findings

See [`ISSUES.md`](ISSUES.md). Concept mapping to start from:
`docs/migration/from-dbos.md` in the core repo — and when a mapping there turns
out to be wrong, that is itself a finding.
