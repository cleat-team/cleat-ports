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
| `tests/test_queue.py` | 103 | **1** — concurrency limits, rate limits, dedup, priority | 0 |
| `tests/test_failures.py` | 43 | **1** — retries, error classification, recovery | 0 |
| `tests/test_workflow_management.py` | 44 | **1** — cancel, resume, fork, list, restart | 0 |
| `tests/test_concurrency.py` | 21 | **1** — concurrent execution and isolation | 0 |
| `tests/test_dbos.py` | 138 | 2 — broad core surface, mixed with SDK ergonomics | 0 |
| `tests/test_async.py` | 57 | 2 — async workflow and step semantics | 0 |
| `tests/test_scheduler.py` | 35 | 2 — cron and scheduled workflows | 0 |
| `tests/test_client.py` | 54 | 3 — client API surface, largely DBOS-specific | 0 |
| **Total in scope** | **495** | | **0** |

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

**Scaffolded. No tests ported yet.** The inventory above is the work plan; the
`Ported` column is the progress metric. Start with priority 1.

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
