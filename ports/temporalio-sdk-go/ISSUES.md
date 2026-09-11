# temporalio-sdk-go: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

---

## 1. Three schedule verbs report success for a name that does not exist

**Class:** Bug
**Upstream test:** `test/integration_test.go::TestScheduleCreate` (the delete half)
**Status:** Open (cleat-team/cleat#1297, filed 2026-09-11)

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

It also blocks a correct behaviour from being tested at all — see the
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
