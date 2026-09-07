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
| `tests/test_queue.py` | 103 | **1** — concurrency limits, rate limits, dedup, priority | 10 |
| `tests/test_failures.py` | 43 | **1** — retries, error classification, recovery | 5 |
| `tests/test_workflow_management.py` | 44 | **1** — cancel, resume, fork, list, restart | 12 |
| `tests/test_concurrency.py` | 21 | **1** — concurrent execution and isolation | 4 |
| `tests/test_dbos.py` | 138 | 2 — broad core surface, mixed with SDK ergonomics | 24 |
| `tests/test_async.py` | 57 | 2 — async workflow and step semantics | 0 |
| `tests/test_scheduler.py` | 35 | 2 — cron and scheduled workflows | 4 |
| `tests/test_client.py` | 54 | 3 — client API surface, largely DBOS-specific | 0 |
| **Total in scope** | **495** | | **62** |

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

**62 ported, 57 passing, 5 skipped** (counted 2026-09-07 with
`grep -hcE '^def test_' tests/test_*.py | awk '{t+=$1} END{print t}'`). The inventory above is the work plan;
the `Ported` column is the progress metric. Priority 1 first, and all four
priority-1 files are started.

This line said **"scaffolded — no tests ported yet"** in `ports/README.md` until
2026-09-07, by which point the port had 53 cases and had found 19 defects. A
status line is a claim with a date on it; this one had neither.

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
| `test_locks.py` | 2 | `test_queue.py` — serialising work through a held key |
| `test_signals.py` (cross-workflow) | 1 | `test_dbos.py` — `send` between workflows |
| `test_continue_as_new.py` | 2 | `test_dbos.py` — bounded history via self-restart |
| `test_defer.py` | 3 | `test_dbos.py` — cleanup that runs once though the body runs twice |
| `test_query_state.py` | 2 | `test_dbos.py` — workflow status readable while running |
| `test_scheduling.py` | 4 | `test_scheduler.py` — cron and delayed invocation |
| `test_plugins.py` | 2 | none — cleat has no upstream analogue; plugin calls through a real worker |
| `test_queues.py` | 4 | `test_queue.py` — deduplication by Idempotency-Key, priority accepted |
| `test_workflow_management.py` | 5 | `test_workflow_management.py` — force-complete, force-fail, and their refusals |
| `test_versions.py` | 2 | none — cleat-specific version reporting across a suspension | It is not a
percentage of upstream: many upstream cases test the DBOS decorator API rather
than an engine property, and those have nothing to port.

The five skips are not unfinished work. Each is a cleat gap this port found,
left visible in the suite with the reason attached rather than deleted, so the
assertion a reader expects is where they expect it:

(This sentence said "three" while the table below listed four and the suite had
five. A count in prose beside the list it counts is a claim that rots twice —
derive it, or do not write it.)

| Skipped | Gap |
|---|---|
| `test_blocked_task_runs_after_the_holder_finishes` | no queueing concurrency limit; a blocked start is rejected rather than deferred |
| `test_a_detached_run_can_be_addressed_by_its_caller` | `RunDetached` returns no handle |
| `test_cancel_stops_a_workflow_that_does_not_cooperate` | no pre-emptive cancellation and no cancelled terminal state |
| `test_the_workflow_id_survives_the_transition` | continue-as-new starts an unlinked new run, so the caller cannot follow the chain to its result (cleat#826) |
| `test_polling_finds_nothing_before_a_signal_and_finds_it_after` | `PollSignal` is not replayed: it re-queries live, so the first poll re-answers `true` after a suspension (cleat#882) |

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
| #827 | continue-as-new wrote a raw result into a JSON column, so the feature failed outright on PostgreSQL — `coerceResultJSON` was called from one write path out of three |
| #826 | a continue-as-new chain is unfollowable: the caller sees `{}` and nothing links to the successor |
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
