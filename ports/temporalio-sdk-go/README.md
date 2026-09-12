# temporalio-sdk-go

Ports of [temporalio/sdk-go](https://github.com/temporalio/sdk-go)'s assertions,
re-expressed against cleat. Upstream source is not vendored; see `UPSTREAM` for
the pin and `../../docs/licensing.md` for why.

The scoping work behind this port is
[`../../docs/temporalio-sdk-go-schedules-survey.md`](../../docs/temporalio-sdk-go-schedules-survey.md),
which reads the 20 `TestSchedule*` cases one at a time. This directory carries
the ones that survived.

## What is here

| test module | cases | answering |
|---|---:|---|
| `schedules_test.go` | 4 | `test/integration_test.go` — `TestScheduleCreateDuplicate`, and the server-side half of `TestScheduleUpdate` |
| `pause_test.go` | 4 | `test/integration_test.go` — the portable half of `TestSchedulePause` |
| `duplicate_start_test.go` | 3 | `test/integration_test.go` — the portable half of the `TestWorkflowIDReuse*` cluster |
| `updates_test.go` | 9 | `test/integration_test.go` — the seven gaps in the `TestUpdate*` cluster |
| `cancellation_test.go` | 1 | `test/integration_test.go` — the only case in the `TestCancel*` cluster no other port reaches |
| `panic_test.go` | 2 | `test/integration_test.go` — `TestPanicFailWorkflow`, plus its control |

Twenty-three **collected** cases from sixteen test functions. Several of the
subtests are controls or discriminators rather than the assertion itself
(below). `go test ./tests/ -list '.*'` prints sixteen function names, which is
the number that looks right and is not the one to quote — checked by running it,
because the arithmetic and the listing disagreed once while this file was being
written.

## The two schedule assertions

**A create under an existing name is refused, and the first schedule is
untouched.** Upstream asserts the refusal (`ErrScheduleAlreadyRunning`); cleat
answers `409 {"detail":"schedule_exists"}`. The port sends a **different**
`def_name` and cron on the second call, because a 409 alone would be satisfied
by an implementation that refused after partially applying — and upstream's
identical-options form structurally cannot see that. What is really being
protected is *the first schedule is never disturbed*, the same property
`ports/durabletask-go/tests/reuse_id_test.go` asserts for idempotency keys.

**An explicit `catch_up_limit: 0` reads back as the default 60.** Upstream sets
`CatchupWindow = 0` and asserts the server substitutes its 365-day default —
"update treats zero as unset". cleat does the same. This pins the behaviour
cleat *has*, not the one the field name suggests: read plainly, `0` means
"never catch up", and an operator who sends it is answered
`201 {"status":"created"}` with no indication that 60 was stored instead.

## The duplicate-start cases

Upstream's `TestWorkflowIDReuse*` cluster walks five reuse and conflict
policies. cleat has one policy and no knob, so the policy selection does not
port — what ports is the observation every one of those cases turns on: **the
second start is answered with what became of the first run.** Upstream reads it
out of a typed error whose message begins "Workflow execution already
*finished*"; cleat carries it in the duplicate response's `status`, with `error`
and `error_code` when the winner failed (cleat#1151).

So the three cases are that distinction in the fields cleat has: a caller
retrying a start it is not sure landed must be able to tell *poll this* from
*fetch the result* from *this will never succeed*.

**Why this is not already covered.** cleat core covers all four arms in
`cmd/cleat-worker/duplicate_start_reports_the_outcome_test.go`. Those are
handler tests over a mock store, and the mock decides both facts under test: it
hands the handler a winner it invented (`&engine.WorkflowInstance{Status:
"failed", Error: "downstream refused", ErrorCode: "E_DOWNSTREAM"}`) and a stub
decides that the second start was a duplicate at all. That is the right shape
for a handler test and it cannot say whether a real key still resolves after the
run it names has reached each of those states.

Two findings came out of running it for real, both in [`ISSUES.md`](ISSUES.md):
the status vocabulary the response actually uses (cleat#1325) and a retention
defect that leaves a key pointing at a deleted run (cleat#1324).

## The update cases

Seven gaps from the `TestUpdate*` cluster, scoped case by case in
[`../../docs/temporalio-sdk-go-updates-survey.md`](../../docs/temporalio-sdk-go-updates-survey.md),
which gives all 27 upstream methods a verdict. **Before this file,
`POST /api/workflows/:id/update/:name` had never been called from any test in
this repository**, across three ports — which is why the cluster was picked.

Two structural differences decide which cases survived, and both make a case
here smaller than its upstream original:

- **There is no wait stage.** Upstream's `WaitForStage: Accepted | Completed` is
  what half the cluster turns on. cleat answers `202` with a `promise_id` and
  settles it later, so *accepted* and *completed* are not distinguishable to a
  caller — only pending and settled.
- **There is no update id.** Upstream addresses a request independently of its
  name and hands that id to the handler. cleat keys a request by
  `(workflow_id, update_name)` and gives the handler the payload alone.

Two findings came out of running it, both in [`ISSUES.md`](ISSUES.md): an update
name is single-use per workflow (cleat#1330), and a sub-millisecond
`AwaitSignals` timeout livelocks the workflow (cleat#1331) — the second found by
the probe rather than by any case.

## What this port deliberately skips, and why

13 of the 20 upstream schedule cases are not portable, and the survey gives each
one a verdict. The three facts behind almost all of them:

- **There is no update route.** `TestScheduleUpdate{,Action,ActionParameter,NewAction,WorkflowActionMemo}` mutate a schedule in place. cleat has create, list, enable, disable, delete. `ports/dbos-transact-py/tests/test_scheduling.py` already covers delete-then-create, which is that property expressed with the operations cleat has.
- **`ScheduleUpdateOptions.DoUpdate` is a client-side callback.** `TestScheduleUpdateError` and `TestScheduleUpdateCancelUpdate` assert the SDK's handling of an error and of `ErrSkipScheduleUpdate` returned by the caller's own function. Nothing reaches the server; these are not engine assertions at all.
- **No search attributes, no memo, no trigger, no backfill, no paginated or filtered list.** That is `TestScheduleTypedSearchAttributes`, `TestScheduleWorkflowActionTypedSearchAttributes`, `TestScheduleTrigger`, `TestScheduleBackfill`, `TestScheduleBackfillCreate` and `TestScheduleList`.

Plus two that are covered elsewhere (`TestScheduleDescribeState` by
`test_scheduling.py`'s policy round-trip) and two that assert cleat's cron
expression is normalised into a structured calendar spec on read
(`TestScheduleDescribeSpec`, `...Cron`, `TestScheduleCalendarDefault`) — cleat
stores and returns the expression verbatim, so there is no normalisation to
assert.

**One case was blocked and is now ported.** `TestSchedulePause` asserts that
pausing an already-paused schedule succeeds as a no-op. That is correct
behaviour and cleat has it — but until cleat#1297 cleat returned the same `200`
whether the row was enabled, already disabled, or **absent**, so a test written
then would have passed for the wrong reason and kept passing if idempotence
broke. cleat#1302 landed the fix (a missing name is now
`404 {"detail":"schedule_not_found"}`) and `pause_test.go` ports it as a **pair**:
the repeat must stay 200, and the same verb on a name that never existed must be
404. Neither half means anything without the other, which is why they are one
function rather than two.

What still does not port from that case is the operator **note** attached to a
pause or unpause; cleat's enable/disable carry no note field.

## The `workflows/` directory

Two packages, built by `scripts/build-workflow.sh`.

`updates` deploys as `tsg_updates` and registers the handlers the update cases
need — two that record, one that echoes its payload, one behind a validator, one
that fails. Its waits are `500*time.Millisecond` and **not** a bare `1000`,
because a bare integer is 1000 *nanoseconds* and cleat#1331 makes that a
livelock rather than an error.

`idreuse` deploys as `tsg_id_reuse`. It waits, then either succeeds or fails on the caller's
instruction, and all three duplicate-start cases share it — the arms differ only
in what the winner is *doing* when the duplicate arrives, and three definitions
would leave "the answer differed because the workflow differed" open.

**The schedule cases still start nothing.** Neither requires a schedule ever to
fire, so both use a cron that cannot fire during a run (`0 3 1 1 *`) and a
`def_name` that need not exist. That is a property of those cases rather than a
stage this port has outgrown.

This is not an assertion that accepting a schedule pointing at a definition
which does not exist is good. cleat accepts it; that is a separate question and
nothing here tests it either way.

## Running

```bash
make -C ../.. deps
make -C ../.. install-cleat
make -C ../.. port PORT=temporalio-sdk-go
```

## Findings

See [`ISSUES.md`](ISSUES.md).
