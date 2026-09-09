# Scoping a second upstream

**Decision (2026-09-09):** finish the 33 portable cases still outstanding in
`dbos-transact-py`, then stop mining it and add a second upstream project.

**Recommendation:** `microsoft/durabletask-go`, Apache-2.0.

This document records why the first upstream is finished, how the candidates
were compared, and what the second one is expected to yield. It is a proposal,
not a port: nothing here has been ported and the yield figures below are
predictions with a stated basis, not measurements.

---

## Why `dbos-transact-py` is finished

All eight files in scope have now been surveyed case by case, by four sessions
working independently. The surveys agree on a shape that the coverage table
does not show:

| upstream file | cases | portable, unported |
|---|---:|---:|
| `test_dbos.py` | 61 | 17 |
| `test_failures.py` | 37 | 5 |
| `test_scheduler.py` | 35 | 5 |
| `test_client.py` | 57 | 3 |
| `test_async.py` | 33 | 1 |
| `test_concurrency.py` | 11 | 1 |
| `test_workflow_management.py` | 46 | 1 |
| `test_queue.py` | 91 | 0 |
| **total** | **371** | **33** |

**Four of those eight figures are not on `develop` yet.** `test_client.py` (3)
is ports#111, `test_async.py` (1) is ports#110, `test_workflow_management.py`
(1) is ports#107, and `test_queue.py` (0) with `test_concurrency.py` (1) are
ports#108 — all open at the time of writing. The other three come from
`WORKLIST.md` as merged. If you are reading this after those land the table is
checkable; if you are reading it before, four rows cite work you cannot see,
and that is the reason to say so rather than let the total read as settled.

The right-hand column is also **not** `cases − cases here`. "Cases here" counts
this port's tests mapped to an upstream file; the surveys count upstream cases
read one at a time. The two disagree — ws3 found `test_client.py` has 13 cases
covered where the inventory credits 8 — so combining them into a percentage
would produce a number with no meaning. 33 is a sum of like with like: cases a
survey read, judged portable, and found unported.

**The `cases` column is a nominal denominator and always was.** What each
survey found is a *ceiling*, not a backlog:

- `test_queue.py` — 72 of 91 need queue controls cleat has no counterpart for.
- `test_client.py` — 30 of 35 declines are **one architectural fact**: DBOS's
  client is a library holding a database connection, cleat's is HTTP.
- `test_async.py` — a third of the file asserts properties of the Python SDK's
  own async machinery, which would still be valid if DBOS's storage layer were
  replaced entirely.
- `test_concurrency.py` — 9 of 11 drive `asyncio.gather` inside one workflow,
  which cleat's determinism analyzer refuses at build time.

None of that is a gap in cleat. It is the boundary of what one upstream, built
on one set of architectural assumptions, can say about a different engine. A
second upstream is worth more than the tail of this one because it brings
different assumptions, not more cases.

---

## Candidates, and the licence filter first

Both repositories are Apache-2.0 and public, and `docs/licensing.md` governs.
Verified by API rather than by reputation, because the last time this was
assumed it was wrong:

| candidate | SPDX | verdict |
|---|---|---|
| `microsoft/durabletask-go` | Apache-2.0 | **eligible** |
| `temporalio/sdk-go` | MIT | eligible |
| `temporalio/sdk-python` | MIT | eligible |
| `uber/cadence` | Apache-2.0 | eligible |
| `conductor-oss/conductor` | Apache-2.0 | eligible |
| `restatedev/sdk-typescript` | MIT | eligible |
| `temporalio/features` | **404 — no licence** | excluded, again |
| `golemcloud/golem` | NOASSERTION | excluded unread |
| `restatedev/restate` | NOASSERTION | excluded unread |
| `inngest/inngest` | NOASSERTION | excluded unread |

`temporalio/features` remains the most attractive suite and remains
unusable — `GET /repos/temporalio/features/license` still returns 404.
`docs/licensing.md` already covers it: describe from prose, never copy.

`NOASSERTION` means GitHub could not match a recognised licence. That is not
proof of a bad licence, but reading a source-available licence carefully enough
to rely on it is work with no payoff while three permissive candidates remain.

---

## Why `durabletask-go`

### 1. Its tests run without external infrastructure

The decisive practical difference. `tests/orchestrations_test.go` builds a task
hub over an **embedded SQLite backend** and runs — no server, no broker, no
container:

```go
client, worker := initTaskHubWorker(ctx, r)
id, err := client.ScheduleNewOrchestration(ctx, "EmptyOrchestrator")
metadata, err := client.WaitForOrchestrationCompletion(ctx, id)
```

Cadence and Conductor are server products whose suites need the full stack.
Temporal's SDK integration tests need a dev server. For a harness that already
juggles three databases and a worker, an upstream that needs nothing extra to
*read and understand* is worth a great deal.

### 2. It is a backend contract, which is cleat's shape

`durabletask-go` separates orchestration semantics from storage behind a
`backend` interface with SQLite and MSSQL implementations. `tests/backend_test.go`
(10 cases) and `tests/runtimestate_test.go` (10 cases) test **that contract
directly**, which is the same layer as cleat's `engine`/store split and the
same multi-dialect concern the nightly matrix exists for.

No file in `dbos-transact-py` tests a storage contract; DBOS's tests go through
the SDK.

### 3. It probes cleat exactly where open questions already are

Not a general argument — three specific cases, read at
`3fe35d93fe1d2bdab21a3d85c14867532adef0b0`:

**`Test_TerminateOrchestration_Recursive`** builds Root → L1 → L2, terminates
the root **parametrised over `recurse` true and false**, and asserts
`assert.NotEqual(t, recurse, executedActivity)` — descendants must run their
activity when recursion is off and must not when it is on. cleat's cancellation
is `WHERE id = $1` with no `parent_workflow_id` traversal on any dialect
(cleat-ports ISSUES 29). Upstream tests both directions of a choice cleat has
not made.

**`Test_SingleActivity_ReuseInstanceID{Ignore,Terminate,Error}`** makes
instance-id reuse a **configurable policy** — ignore the second, terminate the
first, or error. cleat has exactly one behaviour, and this port pinned it today
(`test_a_completed_run_still_answers_for_its_idempotency_key`): the
`idempotency_keys` binding outlives the run by seven days. Three policies
against one behaviour is a far sharper lens than DBOS's single alternative was.
`ReuseInstanceIDIgnore` also asserts the surviving run's `CreatedAt` is the
*first* one's, which is a timestamp assertion cleat can make.

**`Test_SuspendResumeOrchestration`** suspends a running orchestration, raises
events that must **buffer without being consumed**, asserts it does not
complete and reports `SUSPENDED`, then resumes and asserts it consumes the
buffered events. cleat suspends workflows on awaits but has no operator-initiated
suspend, and `cancel` is terminal by design with `resume` rejected deliberately.
This is a direct probe of a decision cleat has already made, which is the most
useful kind of case: it either confirms the decision or names its cost.

### 4. It is a different model from DBOS

DBOS decorates Python functions and enqueues them onto named queues.
durabletask-go registers orchestrators and activities and drives them through a
replay loop with explicit external events, timers and sub-orchestrations. cleat
is closer to the second, which means fewer cases will decline on "cleat has no
such concept" — the failure mode that consumed most of `dbos-transact-py`.

---

## Predicted yield, and how to check it

**This is a prediction, not a survey.** The `dbos-transact-py` surveys exist
because a prediction of this kind was wrong four times. The 26 cases in
`tests/orchestrations_test.go`, classified by whether cleat has the surface at
all:

| | cases | basis |
|---|---:|---|
| cleat has the surface | ~17 | timers, activities, chains, retries, fan-out, sub-orchestrations, continue-as-new, external events, terminate |
| probes a cleat decision | ~5 | recursive terminate ×2, reuse-id ×3 |
| likely declines | ~4 | concurrent timers and `IsReplaying` (determinism analyzer), recursive purge, suspend/resume |

Plus 20 backend-contract cases whose portability is genuinely unknown until
someone reads them against `engine`.

**Do not trust this table.** It was produced by reading 26 test *names* and one
body each for four of them, which is precisely the method that reported
`test_client.py` as 8 covered when it was 13, and `test_async.py` as "mostly
async mirrors" when the mirror bucket was a third of the claimed size. The
first task in the port is the survey, by the method in `WORKLIST.md`:

1. `grep` the new port's `ISSUES.md` before reading upstream.
2. Name-level census — a **lower bound on coverage, never an upper one**.
3. Reconcile against an independent count; a partition that sums correctly is
   not a partition that is right.
4. Separate "cleat lacks the mechanism" from "not an engine assertion at all".

---

## What this does not get us

- **Not a Go-language port.** The port re-expresses assertions against cleat's
  own SDK; upstream's language decides only how the assertions are read.
- **Not more dialect coverage.** The nightly matrix already runs every port on
  all three. A second upstream adds cases, not backends.
- **Not a replacement for `dbos-transact-py`.** Its 33 outstanding cases stay
  outstanding, and its ISSUES ledger stays the record for everything found
  through it.
- **Not free.** `docs/adding-a-port.md` sets out what a new port costs:
  a directory, a harness entry, a fixture set of workflows, and a place in the
  nightly matrix. On the evidence of the first port, the survey is a day and
  the fixtures are the long pole.
