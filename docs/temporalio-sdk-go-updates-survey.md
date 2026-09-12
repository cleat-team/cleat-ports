# `temporalio/sdk-go` — the update cases, case by case

The second cluster read from the upstream
[`next-upstream.md`](next-upstream.md) recommends, after
[the schedule cases](temporalio-sdk-go-schedules-survey.md).

Read at `902937accd7ac67cd8ed16e73b1db2b75cab48a7` (2026-09-12). Licence
re-verified: `GET /repos/temporalio/sdk-go/license` → **MIT**, eligible under
[`licensing.md`](licensing.md).

## Why this cluster, and how it was chosen

Not by name. The schedules survey's closing caution — *"the residue
concentrated in two files of fourteen, and file names did not predict which"* —
applies to clusters inside a file as much as to files. So the 256 methods of
`test/integration_test.go` were bucketed by **the client call their bodies
make**, which is the thing that decides whether a port can drive the case at
all:

| upstream surface | methods | cleat route | port coverage before this |
|---|---:|---|---|
| `ExecuteWorkflow` | 118 | `POST /api/workflows/:name/start` | extensive |
| `SignalWorkflow` | 31 | `POST /api/workflows/:id/signal` | covered |
| **`UpdateWorkflow`** and friends | **27** | `POST /api/workflows/:id/update/:name` | **none** |
| `GetWorkflowHistory` | 25 | `GET /api/workflows/:id/history` | partial |
| `ScheduleClient` | 20 | `/api/schedules` | surveyed |
| `WorkflowService` (raw gRPC) | 17 | — | not portable |
| `CancelWorkflow` | 16 | `POST /api/workflows/:id/cancel` | covered |
| `QueryWorkflow` | 14 | `GET /api/workflows/:id/query?key=` | partial (cleat#1224) |

Updates were the largest cleat surface with **zero** coverage in any port. The
27 is the union of `UpdateWorkflow` (26 methods), `UpdateWithStartWorkflow` and
`NewWithStartWorkflowOperation`; the counts in the other rows are single
methods and do not sum to 256, because one body often calls several.

A correction to my own first pass, recorded because it nearly cost the cluster:
I initially wrote off upstream's validator cases as out of scope, assuming
cleat had no validator concept. It does —
`RegisterUpdateHandler(name, handler, validator)` — and those cases turned out
to be among the more interesting ones. The triage was done on upstream's API
names before reading cleat's.

## Denominator

`test/integration_test.go` is 11,170 lines and carries **256**
`func (ts *IntegrationTestSuite) Test…` methods.

**This survey covers 27 of them** — every method whose body calls
`UpdateWorkflow`, `UpdateWithStartWorkflow` or `NewWithStartWorkflowOperation`.
That is 10.5% of one file of twenty-four in `test/`, and it is not a verdict on
`temporalio/sdk-go`.

**The subtest correction applies here, unlike the schedules cluster.** Two of
the 27 carry `ts.Run` subtests — `TestUpdateBasic` (3) and
`TestUpdateWithStartWorkflow` (9) — so:

    27 methods − 2 with subtests + 12 subtests = 37 collected cases

37 is the figure to quote. The schedules survey checked the same thing and
found zero subtests in range; here it is twelve, which is why it is checked
rather than assumed each time.

## How much was read, and how

| depth | count |
|---|---:|
| body read in full | 27 |
| assertions extracted, body skimmed | 0 |
| name only | 0 |

**Fourteen of the verdicts below were measured against a running worker** on
PostgreSQL at `cleat@develop 6ca1670`, with five purpose-built workflow
packages. Details under "How the measurements were taken".

## cleat's update surface, as it actually is

Measured, not read, except where marked.

| behaviour | cleat |
|---|---|
| send | `POST /api/workflows/:id/update/:name` → `202 {"promise_id":"upd-…"}` |
| read the outcome | `GET /api/workflows/:id/promises` → `promise_name: "update:<name>"`, `status: resolved\|rejected`, `result` / `error_msg` |
| workflow missing | `404 {"error":"workflow not found"}` |
| workflow terminal | `409 "workflow is done and cannot accept updates; it has no future segment to deliver one in"` (cleat#910) |
| same name, first still pending | `409 {"error":"update already pending with name: boom"}` |
| same name, first completed | **`500`** with a raw `pq:` unique-violation string (cleat#1330) |
| no handler registered | `202`, then the promise is `rejected` with `cleat: no update handler registered for "X"` |
| validator refuses | `202`, then `rejected` carrying the validator's own message |
| handler errors | `202`, then `rejected` carrying the handler's message |
| delivery timing | at *dispatch points* only — the SDK calls `DispatchUpdates` before each suspension |
| queue drain | one wake services the **whole** pending queue: six updates posted concurrently were all dispatched and resolved inside one second |
| replay | the handler **and the validator** re-run on every replay; measured stable at 1 run each across ten segments |
| ordering | `ORDER BY priority ASC, created_at` on PostgreSQL; `ORDER BY created_at` on MySQL and SQL Server (read) |

Two structural facts that decide most of the verdicts below:

**There is no "wait stage".** Upstream's `WaitForStage: Accepted | Completed`
is a first-class concept its update cases turn on constantly. cleat's POST
returns `202` immediately and the caller polls the promise, so *accepted* and
*completed* are not distinguishable to a caller — only *pending* and *settled*.

**There is no update id.** Upstream's `UpdateID` identifies a request
independently of its name, is addressable, and is visible to the handler
through `UpdateInfo`. cleat identifies a request by `(workflow_id,
update_name)` and the guest handler receives only the payload string.

## The verdicts

Five verdicts, the four this repo uses plus *present and broken* from the
Cadence work.

| # | upstream case | verdict | note |
|---|---|---|---|
| 1 | `TestUpdateBasic` (3 subtests) | **gap → ported** | the round trip; the wait-stage half does not port |
| 2 | `TestUpdateWithNoHandlerRejected` | **gap → ported** | cleat rejects the promise, not the request |
| 3 | `TestUpdateWithWrongHandleRejected` | **gap → ported** | same shape, and the run still completes |
| 4 | `TestUpdateValidatorRejected` | **gap → ported** | the validator's own message reaches the caller |
| 5 | `TestUpdateRejected` | **gap → ported** | a rejected update leaves the run healthy |
| 6 | `TestWaitOnUpdate` | **gap → ported** | the workflow observes the update's effect |
| 7 | `TestUpdateOrdering` | **gap → ported** | two updates, both applied, in order |
| 8 | **`TestUpdateRejectedDuplicated`** | **present and broken** | **cleat#1330** — see below |
| 9 | `TestMutatingUpdateValidator` | design difference | measured; cleat is safe by construction |
| 10 | `TestUpdateAdmittedNoWorker` | design difference | no wait stage, so nothing to time out on |
| 11 | `TestLongUpdateWaitOnCompleted` | design difference | same |
| 12 | `TestWorkflowExecutionUpdateDeadline` | design difference | the deadline is the client's RPC, which cleat does not have |
| 13 | `TestWorkflowExecutionUpdateCancelled` | design difference | cancelling the *request* has no cleat analogue |
| 14 | `TestUpdateInfo` | **capability gap, not ported** | no update id reaches the guest |
| 15 | `TestUpdateWorkflowCancelled` | satisfied but unobservable | see "What could not be measured" |
| 16 | `TestUpdateHandlerRegisteredLate` | not portable | handlers register during init, before any dispatch point |
| 17 | `TestUpdateAlwaysHandled` | not portable | needs `StartDelay`, which cleat has no equivalent of |
| 18 | `TestUpdateValidatorRejectedFirstWFT` | not portable | same |
| 19 | `TestUpdateSettingHandlerInGoroutine` | not portable | no workflow goroutines |
| 20 | `TestUpdateSettingHandlerInHandler` | not portable | handlers cannot register handlers |
| 21 | `TestUpdateWithMutex` | not portable | `workflow.Mutex`; cleat has `AcquireLock`, a different thing |
| 22 | `TestUpdateWithSemaphore` | not portable | `workflow.Semaphore` |
| 23 | `TestSpeculativeUpdate` | not portable | a server-internal optimisation |
| 24 | `TestUpdateSDKFlag` | not portable | asserts SDK metadata flags in history events |
| 25 | `TestNonDeterminismFailureCauseCommandNotFound` | not portable | needs worker restart mid-run plus a global |
| 26 | `TestResetWorkflowExecutionWithUpdate` | not portable | cleat has no reset |
| 27 | `TestUpdateWithStartWorkflow` (9 subtests) | not portable | no update-with-start |

Totals: **7 gaps**, **1 present-and-broken**, **5 design differences**,
**1 capability gap**, **1 satisfied-but-unobservable**, **12 not portable**.

Compare the two clusters read so far:

| | schedules | updates |
|---|---:|---:|
| methods | 20 | 27 |
| gaps | 3 | 7 |
| present and broken | 1 | 1 |
| satisfied but unobservable | **0** | 1 |
| not portable | 13 | 12 |

The *satisfied but unobservable* bucket that `backend_test.go` filled 4 of 10
with stays near zero for both clusters, which is the third filter's prediction
holding a second time: a suite that drives a server is one a port can drive.

## The defect: an update name is single-use per workflow

Filed as **cleat#1330**.

`workflow_update_requests` has `PRIMARY KEY (workflow_id, update_name)` on all
three dialects, and completion is an `UPDATE … SET status = 'completed'`, not a
delete. So a name is consumed permanently by its first use. Measured against
one healthy `running` workflow, in order:

```
POST .../update/boom            -> 202 {"promise_id":"upd-0955193e…"}
POST .../update/boom  (pending) -> 409 {"error":"update already pending with name: boom"}
POST .../update/boom  (done)    -> 500
  {"error":"pq: duplicate key value violates unique constraint
            \"workflow_update_requests_pkey\" (23505)"}
```

**Upstream is unambiguous that this should work**, which is what makes it a
defect rather than a difference. `TestUpdateRejectedDuplicated`'s own comment:

> Same update ID should be allowed to be reused after the first attempt is
> rejected

and the rest of the cluster treats an update name as a method name invoked
repeatedly — `TestSpeculativeUpdate` sends `"update"` **twelve** times to one
workflow, `TestUpdateOrdering` twice and asserts the result is 2,
`TestUpdateBasic` three times. cleat's own SDK reference describes an update as
*"a request/reply call into a running workflow"* and says nothing about a name
being single-use; its own fixture handler is called `bump` and increments a
counter.

**The dialects disagree, and MySQL's answer is the dangerous one.**
`engine/mysql_ops.go:147` uses `INSERT IGNORE` and discards the result, so a
duplicate is silently dropped, `CreateUpdateRequest` returns `nil`, and the
handler answers `202` with a promise id for a row that does not exist. Measured
on MySQL 8 against the same primary key: second `INSERT IGNORE` → `ROW_COUNT()
= 0`, no error, first payload surviving. No row means `CompleteUpdateRequest`
matches nothing and `failStrandedUpdates` has nothing to sweep — the caller
holds a promise that provably cannot settle, which
`cleat/runtime_updates.go` names as the defect the whole feature exists to
prevent.

Same shape as cleat#1297 (fixed in #1302): a store method discarding
`RowsAffected` so a no-op reports success.

## A second defect, found by the probe rather than by the cases

Filed as **cleat#1331**, and it is not an update defect — it is what the probe
workflow ran into.

`AwaitSignals` guards `timeout <= 0` with a clear error and then converts with
`.Milliseconds()`, which truncates. Every value in `(0, 1ms)` reaches the host
as `timeoutMs = 0` — the value the guard exists to reject — and the workflow
then livelocks: suspended with a deadline of *now*, immediately re-claimable,
replayed to the same step, suspended again, forever.

| timeout | 3 slices | elapsed | generation |
|---|---|---|---|
| 1 µs | never completes | >26 s | 48 and climbing |
| 100 µs | never completes | >26 s | 368 and climbing |
| 1 ms | done | 1 s | 4 |
| 50 ms | done | 2 s | 4 |

One instance reached **generation 4995 in six minutes** — about 14 claims a
second — with its `event_history` constant at 10 rows. `reclaim_count` stays 0,
so no stall detector sees it.

The probe hit this because it copied `h.AwaitSignals([]string{"never"}, 1000)`
from `testdata/updatedispatch/main.go`, whose doc comment calls it *"the shape a
real workflow takes … which is why it is the shape worth pinning"*. It is a
compile-only fixture, so it never runs and never fails.

**This is the reason a port is worth more than a reading.** The update
behaviours were all correct; the bug was in the scaffolding the cases needed,
and no amount of reading `engine/updater.go` would have produced it.

## The design difference worth stating: the mutating validator

Upstream's `TestMutatingUpdateValidator` asserts the **workflow fails** when a
validator mutates workflow state. cleat's SDK reference calls the validator
"read-only" and nothing enforces it, so this looked like a gap.

It is not, and the measurement is the reason. A workflow whose validator
increments a counter, run across ten segments with one update delivered:

```
workflow result: {"marker":"mv","handlerRuns":1,"validatorRuns":1}
promise:         resolved, {"handlerRuns":1,"validatorRuns":1}
```

Stable, and stable for a structural reason. Temporal's validator runs in a
context outside the replayed history, so a mutation there is invisible to
replay and breaks determinism — hence the rule. cleat's validator runs **inside
`runUpdate`, inside the replayed dispatch**: the delivery is an
`update_received` event at a fixed program position, and every replay re-runs
the validator and the handler in the same order. The mutation is reproduced
rather than lost.

So the hazard upstream's rule protects against does not exist here, and
importing the rule would forbid something cleat handles correctly. Recorded
rather than ported, and recorded as *measured* because "read-only by
convention, unenforced" reads like a latent bug until you check.

## The capability gap: no update id reaches the guest

`TestUpdateInfo` sends two updates with client-chosen ids (`testID`,
`notTestID`) and asserts that **the handler returns the id** and that **the
validator can branch on it**. cleat's `RegisterUpdateHandler` gives the handler
`func(payloadJSON string) (string, error)` — the payload and nothing else.

The id exists on the wire: `engine/updater.go`'s `updateDelivery` envelope
carries `request_id`, and `cleat/runtime_updates.go` decodes it and passes it
to `CompleteUpdate`. It stops at the SDK boundary.

Not filed. It is a feature request rather than a defect, and the natural design
question — whether cleat should have request ids distinct from update names at
all — is entangled with cleat#1330's decision about whether names are reusable.
Worth settling together.

## What could not be measured

**`TestUpdateWorkflowCancelled`** — five updates pending, then cancel, then all
five must settle with a cancellation error. cleat has `failStrandedUpdates` for
exactly this transition, and it could not be exercised from here: **one wake
drains the entire pending queue**, measured, so six updates posted concurrently
were all dispatched and resolved inside a second. Producing a genuinely pending
update at the moment of cancellation needs a worker-level intervention — a
stopped worker, or a handler that blocks — that this port has no way to arrange.

Stated rather than skipped, because "we did not test it" and "it cannot be
tested from here" are different claims and only the second is a property of the
port. The first attempt to arrange it also used `POST /api/workflows/:id/terminate`,
which is **404** — the route is `/cancel`; terminate lives elsewhere.

## How the measurements were taken

One worker at `cleat@develop 6ca1670`, PostgreSQL 16, five workflow packages
built through `scripts/build-workflow.sh`:

| package | what it establishes |
|---|---|
| `probe-update` | handler / validator / failing-handler round trips, the 409s, the 500 |
| `probe-update2` | the same with millisecond waits, after cleat#1331 was understood |
| `probe-spin` | the timeout sweep in the table above |
| `probe-mutval` | the mutating validator across ten segments |
| `probe-strand` | six concurrent updates, and that one wake drains them all |

Two notes on method, both learned the hard way in this session:

**The MySQL rows were read from the migration file, not from a container.**
`information_schema` on a long-lived database answers about the database's
first build, not about the current migrations — `CREATE TABLE IF NOT EXISTS`
never adds a constraint to an existing table. On 2026-09-12 two sessions got
**opposite** answers from the same FK query on two containers of different ages.
The `INSERT IGNORE` behaviour *was* measured, on a table created for the
question seconds earlier.

**Every "cleat does X" row above was produced by an HTTP call, not by reading
`engine/`.** The two disagreed once already this session, in the direction that
matters: the duplicate-start status vocabulary reads as `running` in
`server.go`'s contract and is `ready` in every measurement.

## Next step

The seven gaps are worth porting and are the natural follow-on to
`ports/temporalio-sdk-go/tests/duplicate_start_test.go`. They need one workflow
package with a handler, a validator and a failing handler — the `probe-update`
shape — plus a `promises` reader in the harness.

`TestUpdateRejectedDuplicated` should be ported **only once cleat#1330 is
decided**, for the reason the schedules survey gave for deferring
`TestSchedulePause`: written today it would pin a `500` carrying a driver
string, and a test asserting today's answer has to be rewritten by the fix.

Unread and unbucketed: 202 of this file's 256 methods, and 23 of the 24 files in
`test/`. The bucketing table at the top is the cheapest way to pick the next
cluster and took one pass over the file.
