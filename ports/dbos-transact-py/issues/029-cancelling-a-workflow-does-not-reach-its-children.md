## 29. Cancelling a workflow does not reach its children

**Class:** Open question — a divergence nobody has decided on, not a known defect
**Upstream test:** `tests/test_workflow_management.py` — `test_cancel_workflow_children`
**Status:** Open — the behaviour is confirmed; whether it is wrong is the
question this entry exists to put in front of someone

**What upstream asserts**

A three-level tree — parent → child → grandchild, each blocking on an event.
Cancelling the **parent** and then releasing the events, all three observe
cancellation at their next step. Cancellation is a property of the subtree.

**What cleat does — CORRECTED 2026-09-09, the first version of this entry was
wrong**

This entry originally said cancellation reaches exactly one row and that "a
cancelled parent's children run to completion, and so do its grandchildren."
The first half is right about the *cancel* call and the second half is wrong,
because cleat has a propagation mechanism that this entry did not look for.

`CancelWorkflow` does touch exactly one row, on all three dialects:

```sql
UPDATE workflow_instances
SET cancellation_requested = true, cancellation_reason = $2
WHERE id = $1
```

`engine/store_signals.go:22`, `engine/mysql_lifecycle.go`,
`engine/mssql_lifecycle.go`. No traversal of `parent_workflow_id`.

**But `enforceParentClosePolicy` has a REQUEST_CANCEL arm**, present in all
three dialects (`engine/store_lifecycle.go:571`, `mysql_lifecycle.go:1055`,
`mssql_lifecycle.go:1308`), which does exactly the traversal this entry said
was absent:

```sql
UPDATE workflow_instances
SET cancellation_requested = true
WHERE parent_workflow_id = ?
  AND parent_close_policy = 'REQUEST_CANCEL'
  AND status NOT IN ('done', 'failed')
```

So the accurate statement is a conjunction of two things, not one:

| | |
|---|---|
| the default policy is `ABANDON` | `migrations/postgres/001_schema.sql:241`, and `cleat/runtime.go:622` calls it "current default" — children continue running |
| propagation is keyed to parent **close**, not parent **cancel** | ~28 call sites, all of them completion, failure, termination or the defer phase. `CancelWorkflow` is not among them |

**So the divergence is narrower and more specific than this entry claimed.** A
child declared `REQUEST_CANCEL` *is* reached — once the cancelled parent
actually finishes. A default child is not reached at all. Upstream cancels the
subtree immediately and unconditionally; cleat's equivalent is opt-in per child
and deferred until the parent closes.

**How the error happened, since it is the third instance of one pattern.**
`cancel`, `terminate` and `close` are three different events here and the code
uses one vocabulary for all of them. I checked the cancel path, found no
traversal, and generalised to "cleat does not propagate" — a true fact about
`CancelWorkflow` promoted to a false one about the engine. The same conflation
produced a wrong claim about TERMINATE earlier the same day, which cleat#1108
now covers correctly.

**What is still open, and is now the actual question**

A parent blocked *waiting on its children* cannot observe its own cancellation
flag, so it never closes, so the REQUEST_CANCEL arm never fires. That would
make the opt-in mechanism unavailable in precisely the shape that motivates it.

**This is a hypothesis, not a measurement.** What supports it: neither
`engine/children.go` nor `engine/store_children.go` mentions
`cancellation_requested`, so nothing in the child-await path appears to observe
it. What would settle it is a three-level tree with `REQUEST_CANCEL` children,
a parent parked in an await, and a cancel — read the rows. **Not yet run, and
this entry does not claim its outcome.** It is not filed upstream for that
reason; cleat#1108's author was right to measure the neighbouring TERMINATE
case before filing rather than after.

**Why this is not already covered by entry 21**

Entry 21 settles a *different* axis and concludes cleat is right about it: that
cancellation is **cooperative** — a flag a workflow observes at its next step,
rather than a state transition that preempts it. That conclusion is untouched
here.

Propagation is orthogonal. A cooperative flag could be set on every descendant
and remain entirely cooperative: each child would still observe it at its own
next step, still be free to ignore it, still not be preempted. cleat does not set
it, and entry 21 does not say it shouldn't — the question simply never came up.

**Why it is worth deciding rather than just documenting**

The parent usually cannot do it itself. A parent that has been cancelled is, by
entry 21's design, still running until it next checks — but the common shape is a
parent blocked *waiting on its children*, which is exactly when it is not
executing steps and cannot propagate anything. So "the workflow author should
cancel its own children" does not cover the case that motivates the feature.

Against that: cleat has `parent_workflow_id` but a subtree cancel is a recursive
UPDATE per dialect, and a detached child (`tests/test_detached.py`) is a
deliberate shape that must *not* inherit it. Neither is a reason to decline —
they are the reason this is a design question rather than a patch.

**What would close it**

First the measurement above, because the options depend on its outcome.

If an awaiting parent *can* be cancelled and does close, then cleat's answer is
coherent — opt-in propagation, deferred to close — and this becomes a deliberate
difference like entry 21. The port test then asserts that a default child
survives and a `REQUEST_CANCEL` child is flagged once the parent finishes.

If an awaiting parent cannot observe its cancellation, the REQUEST_CANCEL policy
is unreachable in the shape that needs it, and that is a defect rather than a
design question.

The port cannot pick, and until the measurement is run neither can anyone else.
