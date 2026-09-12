# temporalio-sdk-go: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

---

## 1. Three schedule verbs report success for a name that does not exist

**Class:** Bug
**Upstream test:** `test/integration_test.go::TestScheduleCreate` (the delete half)
**Status:** Fixed (cleat-team/cleat#1297, closed 2026-09-12 by cleat#1302) — pinned by `tests/pause_test.go`

**What upstream asserts**

A schedule is deleted, and the *subsequent* describe fails with `NotFound`. The
delete is expected to succeed; the point of the pair is that the schedule is
afterwards genuinely gone.

**What cleat does**

cleat has no describe, so the question was put to the delete directly, against
a fresh database with no schedules in it:

```
DELETE /api/schedules/does-not-exist          -> 200 {"status":"deleted"}
POST   /api/schedules/does-not-exist/disable  -> 200 {"status":"disabled"}
POST   /api/schedules/does-not-exist/enable   -> 200 {"status":"enabled"}
```

Positive control on the same worker: the same three verbs against a schedule
that *does* exist create it, disable it and delete it correctly. So the 200s
above are a silent no-op, not a route that never worked.

`RowsAffected` is discarded in all three store implementations —
`engine/db.go`, `engine/mysql_ops.go`, `engine/mssql_schedules.go`. PostgreSQL
was measured; the other two were read.

**Assessment**

Bug, and the operator case is the argument: `disable` is what someone reaches
for during an incident, and a mistyped name is answered `{"status":"disabled"}`
while the schedule keeps firing. The cross-tenant case answers the same 200.

**Resolved.** cleat#1302 consulted row existence rather than `RowsAffected` — an
existence check in the same statement path, which avoids the MySQL split below.
A missing name is now `404 {"detail":"schedule_not_found"}`, and
`tests/pause_test.go` pins both halves: the repeat stays 200, the missing name
is 404.

One thing the fix turned up that this entry did not predict: **workflow replay
idempotence was resting on the defect.** `DeleteCron`'s call site documented its
dependency on the stores reporting no error for zero rows, because an
at-least-once replayed delete of an already-deleted schedule must not fail the
workflow. The resolution was to have the store report what happened and each
caller decide what it means — 404 for the API, success for a replayed
`DeleteCron`, non-zero exit for the CLI.

It also blocked a correct behaviour from being tested at all — see the
`TestSchedulePause` note in README.md. A peer session measured the fix's trap:
a no-op `UPDATE` on an existing row reports **0** affected on MySQL against
**1** on PostgreSQL and SQL Server, and cleat sets `clientFoundRows` nowhere,
so `RowsAffected == 0 -> 404` would turn a correct idempotent re-disable into a
404 on MySQL only.

---

## 2. `catch_up_limit: 0` is silently replaced by 60

**Class:** Design difference
**Upstream test:** `test/integration_test.go::TestScheduleUpdate` (the zero-is-unset half)
**Status:** Open — pinned by `tests/schedules_test.go`, not filed

**What upstream asserts**

Setting `CatchupWindow` to zero is treated as *unset*, and the server
substitutes its 365-day default.

**What cleat does**

The same, with `catch_up_limit` and 60. Sending `0` reads back `60`; omitting
the field reads back `60`; sending `5` reads back `5`.

**Assessment**

Deliberate difference and it matches upstream, which is why this is not filed
as a bug — but it is recorded because the field name invites the opposite
reading. `catch_up_limit: 0` reads as "never catch up", and the operator who
means that is answered `201 {"status":"created"}` with no indication that 60
was stored. The separate control for "never catch up" is the misfire policy.

Pinned rather than filed, so that a later decision to honour `0` surfaces as a
failing port test rather than as a silent behaviour change for every schedule
created with an explicit zero.

---

## 3. Dead-letter retention leaves the idempotency key behind, and the key then locks the token permanently

**Class:** Bug
**Upstream test:** `test/integration_test.go::TestWorkflowIDReuse*` (reached while porting the cluster)
**Status:** Open (cleat-team/cleat#1324, filed 2026-09-12)

**What cleat does**

`DeleteDeadLetteredWorkflows` deletes `event_history` and `workflow_instances`
and not `idempotency_keys`, on PostgreSQL and MySQL. This is cleat#1255 —
already fixed for the *completed* sweep — surviving in the sibling method.

Measured against PostgreSQL at `develop@6ca1670`, with a run driven into the
DLQ genuinely (retries exhausted, via `ports/dbos-transact-py/workflows/
deadletter`) and the worker started `-dead-letter-retention-days 1`:

```
idempotency_keys for that run, before sweep: 1
sweep -> {"dead_lettered_workflows_deleted":1}
GET /api/workflows/<id>                    -> 404
idempotency_keys for that run, after sweep: 1        <-- leaked
POST .../start  (same Idempotency-Key)
  -> 200 {"already_started":"true","status":"unknown","workflow_id":"<the 404 id>"}
```

Positive control, same worker and same sweep call: a *completed* run's key is
deleted and the retry correctly starts a new run (`201 {"id": ...}`). So both
the sweep and the retry path work; the difference is entirely which of the two
delete methods ran.

**Assessment**

Bug, and worse than #1255 in one specific way: the key is a permanent lock.
`already_started` is returned for as long as the key row lives — 30 days on the
row measured, 7 by schema default — while the run it names is gone, and there is
no request the caller can make to get the work done under that token.

SQL Server is correct here, for a structural reason worth copying: cleat#1265
made both arms call one `deleteWorkflowsBatch` over one child-table list, so the
set cannot diverge between them.

**Not pinned by a test here.** The `status: "unknown"` arm is reachable only
through this defect, so a case asserting today's answer would have to be
rewritten by the fix. The three cases in `tests/duplicate_start_test.go` cover
the other three arms.

---

## 4. The duplicate-start contract names `running` where a sleeping winner is `ready`

**Class:** Bug (documentation and contract)
**Upstream test:** `test/integration_test.go::TestWorkflowIDReuseIgnoreDuplicateWhileRunning`
**Status:** Open (cleat-team/cleat#1325, filed 2026-09-12)

**What upstream asserts**

A second start while the first is still going gets back the first run.

**What cleat does**

The same, and reports the winner's state in `status`. `cmd/cleat-worker/
server.go` states the contract as a three-way table — `running` → poll,
`done` → fetch, `failed` → surface — and then copies `wf.Status` verbatim, a
column with at least seven values.

A workflow parked in a durable sleep is `ready`, not `running`:
`migrations/postgres/003_procedures.sql` sets `status = 'ready'` with a
`next_wake_at` when a segment suspends. Polled every 500 ms across an 8-second
sleep, twenty consecutive samples read `ready` and none read `running`.

**Assessment**

The case the retry mechanism exists for — a client that did not hear the first
answer, retrying while the work is outstanding — most often lands on the one
non-terminal value that contract does not name.

**And the contract is wrong rather than merely thin**, which took a correction
to see. `docs/reference/workflow-lifecycle.md` enumerates all seven statuses and
says in bold that *a sleeping workflow is `ready`, not `suspended`*, with the
`ready` row reading "covers both 'never started' and 'sleeping until
`next_wake_at`'". So the reference document and the handler comment disagree,
and the handler comment is the only place the duplicate response's meaning is
written down — `grep -rn already_started docs/` returns nothing.

The first version of this entry said the vocabulary was undocumented. That grep
answers about the FIELD NAME; I read it as an answer about the STATUS SET, which
I had not grepped for. Recorded because the port's own assertion had the same
defect one layer down, below.

Core cannot disagree about any of this: its test supplies the winner it expects
(`&engine.WorkflowInstance{Status: "running"}`), so the arm a real retry usually
hits has no coverage anywhere.

`tests/duplicate_start_test.go` asserts a **closed set** —
`ready`/`running`/`terminating` — rather than `running`. That is still a real
assertion: `done`, `failed`, a missing field or an unseen status all fail it.

**What the sabotage pass found, and why it is recorded here.** Written without a
guard on the run row, mis-casing the input key `sleepMs` to `sleepms` — which
unbinds the parameter and leaves the zero value — left **all three cases
green**. cleat's `ready` covers "parked in a durable sleep" and "not claimed by
a worker yet" alike, so a run that finished in 50 ms was indistinguishable from
one sleeping for twenty seconds. The arm now POLLS the run row until
`next_wake_at - started_at` clears half the requested sleep, failing at once if
`completed_at` appears instead, and the same sabotage fails it in under a second
naming the measured `completed_at`. A status vocabulary that conflates two states
costs a test its discriminating power as well as a client its branch.

**Polling rather than one read, and that was a second bug in the same guard.**
`started_at` is written when a worker CLAIMS the run; `next_wake_at` only moves
when the segment SUSPENDS. A single read taken between those two moments sees a
claimed run that has not parked yet and fails. Green in isolation and on repeat,
red once in a full-suite run right after a redeploy — when the first module load
widens that window. Found by running the suite six times rather than once, which
is the habit the first bug in this guard earned.

---

## 5. An update name is single-use per workflow, and the three dialects disagree about the second request

**Class:** Bug
**Upstream test:** `test/integration_test.go::TestUpdateRejectedDuplicated`
**Status:** Open (cleat-team/cleat#1330, filed 2026-09-12)

**What upstream asserts**

That a rejected update's id can be reused. Its own comment:

> Same update ID should be allowed to be reused after the first attempt is
> rejected

and the rest of the cluster treats an update name as a method name invoked
repeatedly — `TestSpeculativeUpdate` sends `"update"` **twelve** times to one
workflow, `TestUpdateOrdering` twice and asserts the result is 2.

**What cleat does**

`workflow_update_requests` is keyed `PRIMARY KEY (workflow_id, update_name)` on
all three dialects and completion is an `UPDATE … SET status = 'completed'`, not
a delete, so the name is consumed permanently. Measured against one healthy
`running` workflow:

```
POST .../update/boom            -> 202 {"promise_id":"upd-0955193e…"}
POST .../update/boom  (pending) -> 409 {"error":"update already pending with name: boom"}
POST .../update/boom  (done)    -> 500
  {"error":"pq: duplicate key value violates unique constraint
            \"workflow_update_requests_pkey\" (23505)"}
```

The `409` guard reads `GetPendingUpdateRequests`, which filters
`status = 'pending'`, so it covers only the brief window before dispatch. The
common case — a caller resending after the first finished — falls through to the
primary key.

On MySQL `engine/mysql_ops.go:147` uses `INSERT IGNORE` and discards the result,
so the duplicate is dropped silently, `CreateUpdateRequest` returns `nil`, and
the handler answers `202` with a promise id for a row that does not exist.
Measured on MySQL 8 against the same key, on a table created for the question:
second `INSERT IGNORE` → `ROW_COUNT() = 0`, no error, first payload surviving.

**Assessment**

Bug. Nothing documents the constraint: `docs/reference/sdk-api.md` describes an
update as "a request/reply call into a running workflow", and cleat's own
fixture handler is called `bump` and increments a counter — a shape that can be
invoked exactly once.

**How it shapes this port.** `workflows/updates` registers `apply_one` and
`apply_two` rather than sending one name twice, and the validator case uses two
separate runs. The divergence is stated in both files rather than worked around
silently.

**Not pinned by a test.** A case asserting today's answer would pin a `500`
carrying a driver string, and the fix will rewrite it — the same reason
`TestSchedulePause` was deferred until cleat#1297 landed.

---

## 6. A sub-millisecond `AwaitSignals` timeout livelocks the workflow

**Class:** Bug
**Upstream test:** none — found by the probe, not by a case
**Status:** Open (cleat-team/cleat#1331, filed 2026-09-12)

**What cleat does**

`cleat/runtime_signals.go:220` guards `timeout <= 0` with a clear error and then
converts with `.Milliseconds()`, which truncates. Every value in `(0, 1ms)`
reaches the host as `timeoutMs = 0` — the value the guard exists to reject — and
`engine/signaller.go:275` then suspends with a deadline of *now*. The run is
immediately re-claimable, replays to the same step, and suspends again.

| timeout | 3 slices | elapsed | generation |
|---|---|---|---|
| 1 µs | never completes | >26 s | 48 and climbing |
| 100 µs | never completes | >26 s | 368 and climbing |
| 1 ms | done | 1 s | 4 |
| 50 ms | done | 2 s | 4 |

One instance reached **generation 4995 in six minutes** — about 14 claims a
second — with `event_history` constant at 10 rows. `reclaim_count` stays 0, so
no stall detector sees it, and nothing is logged.

`DurableSleep` truncates identically and is fine: a 0 ms sleep is "don't wait".
This is specific to the signal wait, where a 0 ms wait has no exit.

**Assessment**

Bug, and the reason it is recorded in a port's findings rather than only
upstream: **the probe hit it, no case did.** Every update behaviour the cluster
asks about turned out correct. The bug was in the scaffolding those cases
needed — the probe copied `h.AwaitSignals([]string{"never"}, 1000)` from
`testdata/updatedispatch/main.go`, a compile-only fixture whose doc comment
calls it "the shape a real workflow takes … which is why it is the shape worth
pinning".

`AwaitCondition` passes its public `pollInterval` straight through with no
validation, so a sub-millisecond poll interval livelocks a workflow from inside
library code.

**Pinned indirectly.** `workflows/updates` says `500*time.Millisecond` with a
comment explaining why, so the next person copying from this port copies the
correct form.
