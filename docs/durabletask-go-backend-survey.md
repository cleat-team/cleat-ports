# `durabletask-go` — the backend contract, case by case

The companion to
[`durabletask-go-orchestrations-survey.md`](durabletask-go-orchestrations-survey.md).
That file covers `tests/orchestrations_test.go`; this one covers
`tests/backend_test.go` and `tests/runtimestate_test.go` — 10 cases each.

Read at `3fe35d93fe1d2bdab21a3d85c14867532adef0b0`.

## Why this half first

cleat-agent1-31's recommendation, and it holds up: **this is the layer nothing
in `dbos-transact-py` touches.** DBOS's tests go through its SDK. durabletask-go
separates orchestration semantics from storage behind a `backend` interface and
tests that contract directly — which is the same split as cleat's
`engine`/store, and the same multi-dialect concern the nightly matrix exists
for.

It is also the layer where every field defect found in cleat today lived:
`completed_at`, `started_at`, `parent_workflow_id`, `created_at` and
`pending_terminal_status` were all store-to-API plumbing (cleat#1091, #1090,
#1103, #1105).

## Denominator

`^func Test` and a strict-signature match both give **10 and 10**. No `t.Run`
in either file, so definitions equal collected cases here — unlike
`orchestrations_test.go`, where four `range []bool` loops make 26 functions into
30 cases.

Stating that because the same check on the other file was wrong in
`next-upstream.md` until #131.

## How much of this was read, and how

| depth | count |
|---|---:|
| body read in full | 2 |
| assertions and `be.*` call sites extracted | 8 |
| name only | 0 |

**No case here is classified from its name.** That is the method that took the
`test_dbos.py` figure from 17 to 9 to 2, and the correction that mattered was
not the count — it was that "portable" is a claim about **cleat** while the
verification had established something about the **upstream**.

## `tests/backend_test.go`

| case | verdict | what settles it |
|---|---|---|
| `Test_NewOrchestrationWorkItem_Single` | engine | fetch a work item, assert instance id and name |
| `Test_NewOrchestrationWorkItem_Multiple` | engine | same, several queued |
| `Test_CompleteOrchestration` | engine | `IsComplete` / `IsRunning` after completion |
| `Test_ScheduleActivityTasks` | engine | asserts `ErrNoWorkItems` on an empty queue |
| `Test_ScheduleTimerTasks` | engine | same, for timers |
| `Test_AbandonOrchestrationWorkItem` | **engine, novel** | abandon then refetch immediately |
| `Test_AbandonActivityWorkItem` | **engine, novel** | same for activities |
| `Test_PurgeOrchestrationState` | engine | 163 lines, the largest; purge and retention |
| `Test_UninitializedBackend` | **not an engine assertion** | `ErrNotInitialized` before init — Go object lifecycle |
| `Test_GetNonExistingMetadata` | already covered | `test_api_surface.py::test_an_unknown_run_is_a_clean_404_on_every_read_path` |

## `tests/runtimestate_test.go`

Ten cases over the replay state machine: new, completed, completed
sub-orchestration, continue-as-new, create timer, schedule task, create
sub-orchestration, send event, `StateIsValid`, `DuplicateEvents`.

`Test_DuplicateEvents` asserts `backend.ErrDuplicateEvent`. The Go error value
does not port; **the property does** — a duplicate event in history must be
rejected. It also carries an upstream `TODO` admitting it covers one duplicate
type and not task completion, external events or sub-orchestration.

## The two worth building first

**`AbandonOrchestrationWorkItem` then immediate refetch.** cleat's analogue is a
released claim becoming re-claimable, which is exactly what the generation fence
guards — and nothing in `dbos-transact-py` exercises release-then-reclaim as a
*deliberate* operation. The only version the port has is the reaper's
involuntary one after a crash, which conflates "released" with "the owner died".

**`ErrNoWorkItems` as a distinguishable outcome.** An empty queue must not read
as an error. That is the same classification question as
`test_retries.py::test_a_permanent_failure_is_not_reported_as_an_exhausted_budget`
one layer down: cleat's claim path returns no rows, and whether a caller can
tell "nothing to do" from "something went wrong" is unasserted.

## What this adds up to, and what it does not

**7–8 of 10 in `backend_test.go` are engine assertions**, against
`test_client.py`'s 3-of-57 and `test_async.py`'s 1-of-33. That is the first
quantitative support for `next-upstream.md`'s claim that a backend contract is
closer to cleat's shape than a client library is.

It is **not** a portability count. Every row above says whether the case asserts
something about an engine, which is a claim about **durabletask-go**. Whether
cleat can express each one is a separate judgement requiring cleat's surface,
and for `runtimestate_test.go` in particular it is unmade: those ten test a
replay state machine directly, and whether cleat's event history exposes an
equivalent seam is not something this survey establishes.

Anyone quoting a portable figure from this file should not.
