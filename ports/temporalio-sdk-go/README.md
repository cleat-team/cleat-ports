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

Four **collected** cases from two test functions: the second is three subtests,
and two of those three are controls rather than the assertion (below). `go test
./tests/ -list '.*'` prints the two function names, which is the number that
looks right and is not the one to quote.

## The two assertions

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

**And one is blocked rather than declined.** `TestSchedulePause` asserts that
pausing an already-paused schedule succeeds as a no-op. That is correct
behaviour and cleat has it, but cleat currently returns the same `200` whether
the row was enabled, already disabled, or **absent** (cleat#1297) — so a test
written today would pass for the wrong reason and would keep passing if
idempotence broke. It becomes portable when #1297 lands.

## Why there is no `workflows/` directory

Neither assertion requires a schedule ever to fire, so both use a cron that
cannot fire during a run (`0 3 1 1 *`) and a `def_name` that need not exist.
That is a property of these two cases, not a design: the first case that needs
a schedule to *start* something will need a workflow package and
`scripts/build-workflow.sh`, the way the other Go ports do.

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
