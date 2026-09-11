# `temporalio/sdk-go` — the schedule cases, case by case

The first corpus read from the upstream
[`next-upstream.md`](next-upstream.md) recommends. That document ends with:

> The right first step is one file, read case by case, with the four verdicts
> this repo now uses [...] I have not read the suite.

This reads **one cluster of one file**, not the file. Saying so first because
the denominator is the thing surveys here keep getting wrong.

Read at `902937accd7ac67cd8ed16e73b1db2b75cab48a7` (2026-09-11).
Licence re-verified the same day: `GET /repos/temporalio/sdk-go/license` →
**MIT**, eligible under [`licensing.md`](licensing.md).

## Denominator, and what fraction of it this is

`test/integration_test.go` is 11,170 lines. Three derivations of its case count:

| derivation | result |
|---|---:|
| `^func Test` | 1 — the suite runner, `TestIntegrationSuite` |
| `^func \(ts \*IntegrationTestSuite\) Test` | **256** |
| `ts.Run("` inside the file | 40 named subtests |

So 256 methods is the figure to quote, and it is a **lower bound** on collected
cases: 40 subtests sit inside some of them. The correction is not applied here
because none of the 40 falls inside the range this survey covers — every
`ts.Run` line in the file is outside lines 6335–7500 — so for **this cluster**
functions equal collected cases, checked rather than assumed.

**This survey covers 20 of those 256: every `TestSchedule*` method.**
That is 7.8% of one file of twenty-four in `test/`. It is not a verdict on
`temporalio/sdk-go` and must not be quoted as one.

Why this cluster first: cleat has schedules, they have an HTTP surface, and
they are implemented three times — `engine/db.go`, `engine/mysql_ops.go`,
`engine/mssql_schedules.go` — which is the shape the nightly matrix exists for.
`next-upstream.md`'s third filter asks for the intersection of *engine-ness* and
*HTTP-observability*; schedules are one of the few cleat surfaces that sit
squarely in it.

## How much was read, and how

| depth | count |
|---|---:|
| body read in full | 12 |
| assertions extracted, body skimmed | 8 |
| name only | 0 |

**And nine of the verdicts below were measured against a running worker**, not
derived from reading cleat's source. Details under "How the measurements were
taken".

## cleat's schedule surface, as it actually is

Derived from `cmd/cleat-worker/app.go` and `cmd/cleat-worker/server.go` at
cleat `develop@1f11300`, then exercised:

| verb | route |
|---|---|
| create | `POST /api/schedules` |
| list | `GET /api/schedules` |
| enable / disable | `POST /api/schedules/{name}/enable`, `.../disable` |
| delete | `DELETE /api/schedules/{name}` |

There is **no single-schedule GET**, no update, no trigger-now, and no
backfill. A "describe" is a list read filtered by name. That one fact decides
eleven of the twenty verdicts, so it is stated before the table rather than
repeated in it.

## The verdicts

Five verdicts, the fifth from the Cadence corpus:
**gap** · **already covered** · **not portable** · **satisfied but unobservable
from here** · **present and broken**.

| upstream case | verdict | basis |
|---|---|---|
| `TestScheduleCreate` | **split** — the create/default half is *already covered*, the delete half is **present and broken** | see below |
| `TestScheduleCreateDuplicate` | **gap — portable and novel** | cleat refuses the second create with `409 schedule_exists` and leaves the first row's definition untouched. Measured. No test in this repo asserts it: the one that sounds like it, `test_replacing_a_schedule_under_one_name_replaces_what_it_starts`, does delete-then-create and says so in its docstring |
| `TestScheduleUpdate` | **split** — the zero-is-unset half is a **gap, portable and novel**; the rest is *not portable* | upstream sets `CatchupWindow = 0` and asserts the server substitutes the 365-day default. cleat does the same thing with `catch_up_limit`: sending `0` reads back as `60`. Measured. The remaining assertions are about `ScheduleUpdateOptions.DoUpdate`, a client-side read-modify-write callback with no cleat counterpart |
| `TestScheduleUpdateError` | **not portable — not an engine assertion** | asserts the SDK propagates an error returned by the caller's own `DoUpdate` callback. Nothing reaches the server |
| `TestScheduleUpdateCancelUpdate` | **not portable — not an engine assertion** | asserts `temporal.ErrSkipScheduleUpdate` from the callback suppresses the request. Nothing reaches the server |
| `TestScheduleUpdateAction` · `...ActionParameter` · `...NewAction` · `...WorkflowActionMemo` | **not portable** ×4 | all four mutate a schedule's action in place. cleat has no update route; the property expressed with the operations cleat has is delete-then-create, which `test_scheduling.py` already covers |
| `TestSchedulePause` | **split** — idempotence is a **gap**, the note field is *not portable* | upstream asserts pausing a paused schedule succeeds as a no-op, and that pause/unpause carry an operator **note**. cleat has enable/disable and no note column. Idempotence is askable and unasserted; see the caveat below |
| `TestScheduleTrigger` | **not portable** | no trigger-now. The nearest cleat surface is the misfire/catch-up path, which fires on a clock rather than on demand |
| `TestScheduleBackfill` · `TestScheduleBackfillCreate` | **not portable** ×2 | no backfill, at create time or after. `catch_up`/`catch_up_limit` is a bounded automatic version of the same idea and is already covered by `test_misfire.py` |
| `TestScheduleList` | **not portable** | the assertions are pagination (`PageSize: 1`) and a search-attribute `Query`. `GET /api/schedules` has neither. Adjacent to cleat#1182 (workflows capped at 100 with no paging), which is filed and closed for workflows only |
| `TestScheduleDescribeState` | **already covered** | policy and state round-trip through the API — `test_the_schedule_policies_round_trip_through_the_api` and `test_a_schedule_created_without_policies_carries_the_documented_defaults`. The parts that are not covered are `Memo`, `StaticSummary`, `StaticDetails`, `RemainingActions` and `Note`, none of which cleat has |
| `TestScheduleDescribeSpec` · `TestScheduleDescribeSpecCron` | **not portable** ×2 | both assert that a partial spec is **normalised into a fully-populated calendar structure on read** — `Hour: {Start: 12}` comes back as `{Start: 12, End: 12, Step: 1}`. cleat stores and returns the cron expression verbatim, so there is no normalisation to assert. See the cron-dialect note below, which came out of trying to port this |
| `TestScheduleCalendarDefault` | **not portable** | same normalisation property, at create time |
| `TestScheduleTypedSearchAttributes` · `TestScheduleWorkflowActionTypedSearchAttributes` | **not portable** ×2 | cleat has no search attributes on schedules or on the workflows they start |

Totals: **3 gaps** (two whole, one half), **2 already covered**, **13 not
portable**, **1 present and broken**, **0 satisfied-but-unobservable**.

The zero in that last bucket is worth one line, because it is the bucket
`backend_test.go` filled 4 of 10 with. Schedules are administered over HTTP by
design, so the surface a port can drive is the whole surface there is — which
is the case *for* picking a corpus by the third filter rather than by
engine-ness.

## The defect: three verbs report success for a schedule that does not exist

`TestScheduleCreate`'s last four lines are the ones that found it:

```go
err = handle.Delete(ctx)
ts.NoError(err)

description, err = handle.Describe(ctx)
ts.IsType(&serviceerror.NotFound{}, err)
ts.Nil(description)
```

Deleting is expected to succeed, and the **subsequent** describe is expected to
fail with `NotFound`. cleat cannot fail the second half, because it has no
describe — but asking the first half of the question against a name that was
never created gives:

```
DELETE /api/schedules/does-not-exist  ->  200 {"status":"deleted"}
POST   /api/schedules/does-not-exist/disable -> 200 {"status":"disabled"}
POST   /api/schedules/does-not-exist/enable  -> 200 {"status":"enabled"}
```

All three store methods discard the result of their statement on all three
dialects — `_, err = tx.ExecContext(...)` in `engine/db.go`,
`engine/mysql_ops.go` and `engine/mssql_schedules.go` — so `RowsAffected` is
never consulted and zero rows is indistinguishable from one.

The operator reading is the reason this matters more than a status code:
**`disable` on a mistyped name answers `{"status":"disabled"}` while the
schedule keeps firing.** The same 200 is returned when the name belongs to
another tenant, which `engine/mssql_admin_login_schedule_tenant_test.go`
already exercises for isolation — correctly, and while expecting the nil error
that makes the report wrong.

Filed as cleat#1297.

**This is the `harness-noop` shape from ports#173/#175/#178/#181, in cleat
rather than in the harness**: an operation that changes state reporting the exit
status of the attempt instead of the postcondition. The port-side rule those
PRs settled on transfers unchanged — *verify the state changed*.

## A caveat on the idempotence half of `TestSchedulePause`

Pausing a paused schedule returning 200 is upstream's asserted behaviour and is
**correct**. cleat returning 200 for `disable` on an already-disabled schedule
is equally correct. The two are indistinguishable from outside, and the defect
above is the reason: cleat returns the same 200 whether the row was disabled,
was already disabled, or does not exist.

So this case is only portable *after* cleat#1297 — a test written today would
pass for the wrong reason, and would keep passing if the fix broke idempotence.
Recorded here rather than left for the next reader to rediscover.

## The cron dialect, measured while trying to port `DescribeSpecCron`

Upstream's spec is `0 12 * * MON`. cleat refuses it:

| expression | result |
|---|---|
| `0 12 * * 1` | 201 |
| `*/5 * * * *` | 201 |
| `0 12 * * MON` | 400 `cron: day-of-week field: "MON" is not a number` |
| `0 12 * * MON-FRI` | 400 — same |
| `@daily` | 400 `cron: "@daily" has 1 field(s), want 5` |

**Not a defect and not filed.** Every refusal is a 400 at the door naming the
field and the reason, which is what cleat#996 and the validation comment in
`handleCreateSchedule` were both about. It is recorded because it bounds what
any future schedule port can send, and because "the port used a spec cleat
rejects" would otherwise be diagnosed as a cleat bug by whoever hits it.

## How the measurements were taken

Nine verdicts above say "measured". Against:

- cleat `develop@1f11300`, **built from a fresh clone in this session**, not
  from a long-lived checkout — [`cleat-ports-main-is-a-decoy`'s stale-tree
  failure](https://github.com/cleat-team/cleat-ports) is the reason that is
  spelled out.
- A **fresh** `postgres:16` container created for the probe and destroyed after,
  so no schedule predated it. A long-lived database would not have answered the
  question: every probe here is about the difference between zero rows and one.
- A worker on a port no other session was listening on, with
  `-require-auth=false -rls-check=off`. Both flags are off the default path;
  neither touches the schedule handlers, which take the same
  `scopedStore` → store-method path in either configuration.

**The positive control, which is the part that makes the negative results
mean anything.** Before concluding that a 200 on a missing name is a no-op, the
same three verbs were run against a schedule that *did* exist:

```
POST   /api/schedules            -> 201, and the row appears in the list
POST   /api/schedules/x/disable  -> 200, and the row reads enabled=false
DELETE /api/schedules/x          -> 200, and the list is empty
```

So the routes work, and the 200s on a missing name are a silent no-op rather
than a route that does nothing at all. Without that control the finding would
rest on an empty result — which is the thing this repo's notes say is the most
persuasive wrong answer there is.

**PostgreSQL only.** The MySQL and SQL Server claims are from reading the two
other store implementations, which have the identical `_, err = ...` shape. That
is a strong inference and not a measurement, and the difference is stated
because the last three times a dialect was assumed to match it did not.

## What this says about the upstream, and what it does not

**Says:** the corpus is readable, the cases are self-contained, and the cluster
yielded one filed defect and two novel portable assertions from twenty cases.
That is a better hit rate than `backend_test.go` (10 cases → 0 portable gaps)
and comparable to the productive Cadence files.

**Does not say:** anything about the other 236 cases in this file, or the other
23 files. The clusters visible by name — `TestUpdate*` (~28), `TestLocalActivity*`
(~25), `TestSlot*`/`TestResourceBased*` (~10), `TestOpenTelemetry*` (~6),
`TestSession*` (~7) — are named for Temporal SDK concepts cleat does not have,
and a name-level guess about them is exactly what this repo's own history says
not to publish. `TestChildWF*`/`TestWorkflowIDReuse*` are the clusters most
likely to repeat this one's yield, on the strength of cleat having the surface
and `durabletask-go`'s survey having found `parent_close_policy` untested.

## Next step

A `ports/temporalio-sdk-go/` directory, per
[`adding-a-port.md`](adding-a-port.md), carrying the three assertions this
survey found portable:

1. a duplicate create is refused and the first schedule is untouched;
2. `catch_up_limit: 0` reads back as the default;
3. after cleat#1297, that enable/disable are idempotent on a schedule that
   exists **and** refuse one that does not.

Deliberately not done in that PR: the survey was its work product, and a port
directory is a harness entry, a fixture set and a nightly matrix slot.

**Done 2026-09-11: [`ports/temporalio-sdk-go/`](../ports/temporalio-sdk-go/)**
carries assertions 1 and 2 as four collected cases, all passing on PostgreSQL
through `make port PORT=temporalio-sdk-go` against cleat `develop@14bec5d`, and
every assertion in it was sabotaged individually and observed to go red before
the PR was opened — including one that a `t.Fatalf` above it had masked on the
first attempt.

Assertion 3 stays blocked on cleat#1297, for the reason given above: written
today it would pass for the wrong reason.

It needs **no `workflows/` directory**, which was not expected when this survey
was written. Both assertions are about the schedule ROW, so a cron that cannot
fire during a run and a `def_name` that need not exist are enough. The first
case that needs a schedule to *start* something changes that.
