# Porting work-lists

One section per upstream file that has been read case by case. Each says, for
every upstream case, what cleat surface it would need and whether that surface
is present, absent, or differently shaped — so the next porting effort can start
from the answer rather than redo the reading.

**A section that is mostly "already covered" is a result, not a null result.** It
says the next effort should go elsewhere, which is otherwise unknown either way.

**Four verdicts, not three.** *Portable*, *already covered*, and *needs something
cleat lacks* are the three a work-list obviously needs. The fourth is
**answered differently on purpose** — cleat does not do this, deliberately, and
the decision is recorded. It is separated out because it is the one most likely
to be misread as an absence by someone skimming for gaps, and *"we decided
against this, here is why"* is a stronger statement than *"lacks it"*.
Suggested by the rcownie-ef session while reading `test_dbos.py`.

**Blockers concentrate; they do not spread.** Three files have now been read by
three sessions independently, and each bottoms out on two or three specific
missing verbs rather than on a thin scatter across the surface:

| file | cases | the blockers, and how much they account for |
|---|---:|---|
| `test_failures.py` | 37 | per-call timeout, transactions, SQLite backend |
| `test_scheduler.py` | 35 | `apply_schedules` 8 · `trigger_schedule` 6 · `backfill_schedule` 2 — 24 of 35 (**the 5 portable are ported**) |
| `test_dbos.py` | 61 | `@DBOS.transaction` 16 · step listing 7 · bulk send 5 · fork 3 — 42 of 61 |
| `test_client.py` | 57 | transactional enqueue 16 · client-library internals 14 · otel/identity/send-key 5 — 35 of 57 |

That is more actionable than a per-file portable count: **adding one verb unblocks
a double-digit number of cases in a single file.** A reader deciding what to build
should start here rather than with the totals.

Two of those blockers are recorded nowhere but a migration guide — see the
`test_dbos.py` section on `@DBOS.transaction`.

Upstream: `dbos-inc/dbos-transact-py`, MIT. Not vendored — this port re-expresses
assertions rather than copying source.

---

## The work-lists

One file per upstream file, under `worklists/`. Split for the same reason as
the entries above: every section was an end-of-file append and collided with
every other. This table is generated and checked.

| Upstream file | Section |
|---|---|
| `tests/test_failures.py` | [37 cases, read at `833794f7`](worklists/test-failures.md) |
| `tests/test_scheduler.py` | [35 cases, read at `833794f7`](worklists/test-scheduler.md) |
| `tests/test_dbos.py` | [61 cases, read at `833794f7`](worklists/test-dbos.md) |
| `tests/test_client.py` | [57 cases, read at `833794f7`](worklists/test-client.md) |
| `tests/test_async.py` | [33 cases, read at `833794f7`](worklists/test-async.md) |
| `tests/test_queue.py` | [91 cases, read at `833794f7`](worklists/test-queue.md) |
| `tests/test_concurrency.py` | [11 cases, read at `833794f7`](worklists/test-concurrency.md) |
| `tests/test_workflow_management.py` | [46 cases, read at `833794f7`](worklists/test-workflow-management.md) |
