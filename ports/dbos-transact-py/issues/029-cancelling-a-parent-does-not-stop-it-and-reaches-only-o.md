## 29. Cancelling a parent does not stop it, and reaches only opt-in children

**Class:** Open question — a divergence nobody has decided on, not a known defect
**Upstream test:** `tests/test_workflow_management.py` — `test_cancel_workflow_children`
**Status:** Open — measured on postgres with an ABANDON control; the one
remaining question is whether `AwaitChild` should observe cancellation

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

**MEASURED 2026-09-09, and it overturned the hypothesis this entry had put in
its place**

The previous revision guessed that a parent parked in a child await could never
observe its cancellation, making `REQUEST_CANCEL` unreachable in the shape that
motivates it. Run it and that is wrong. Parent with two `REQUEST_CANCEL`
children, awaiting only the short one, cancelled 5s in:

| | outcome | when |
|---|---|---|
| parent | **completed normally**, `outcome: completed` | 20.1s, its own schedule |
| long child, `REQUEST_CANCEL` | **cancelled** | 6.75s -- ~1.75s after the cancel |
| long child, `ABANDON` (control) | completed | ran its full 120s |

So propagation works and it is prompt. What cancelling a parked parent does
*not* do is stop the parent: `AwaitChild` does not check `PollCancellation`, so
the await returns its child's result and the parent finishes as though nothing
had happened. That part of the original entry survives.

**What is still open: when the flag is WRITTEN.** Two probes disagree.
A polling child observes cancellation ~1.75s after the cancel, but sampling
`cancellation_requested` directly once per second for a NON-polling child
showed the column flipping only when the parent closed, ~15s later.
`PollCancellation` is `CheckCancellation` (`engine/store_signals.go:34`), which
reads the workflow's own column with no parent traversal -- so both cannot
describe one mechanism, and one of the two probes is measuring something other
than what it appears to. **Not resolved, and the ported tests are written to
survive either answer.**

**Three revisions, and the shape of the errors is the point.** Read-only: "no
propagation exists" -- wrong, there is a REQUEST_CANCEL arm. Reasoned-from-code:
"propagation is deferred to parent close, so it is unreachable here" -- wrong,
it arrives in under two seconds. Only the run with an ABANDON control produced
something that held. And the first attempt at that control passed while testing
the wrong binary, because editing the policy in place redeployed under the same
`v1` and the run kept the old module.

**What would close it**

The measurement is done and it is narrower than either branch this entry
previously offered. cleat's cancellation is opt-in per child and prompt for
those that opted in; what it does not do is interrupt the parent.

So the question left for someone to decide is a single one: **should `AwaitChild`
observe cancellation?** Today a cancelled parent blocked on a child keeps
waiting for it, and the cancel has no effect on the parent at all -- only on
children that asked for one. Upstream's parent stops.

Either answer is defensible and the port asserts neither. `tests/test_cancel_propagation.py`
records the current behaviour with its ABANDON control, so a change here fails
visibly rather than silently.
