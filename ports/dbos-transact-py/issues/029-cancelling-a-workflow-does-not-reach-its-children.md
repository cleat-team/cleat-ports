## 29. Cancelling a workflow does not reach its children

**Class:** Open question — a divergence nobody has decided on, not a known defect
**Upstream test:** `tests/test_workflow_management.py` — `test_cancel_workflow_children`
**Status:** Open — the behaviour is confirmed; whether it is wrong is the
question this entry exists to put in front of someone

**What upstream asserts**

A three-level tree — parent → child → grandchild, each blocking on an event.
Cancelling the **parent** and then releasing the events, all three observe
cancellation at their next step. Cancellation is a property of the subtree.

**What cleat does**

Cancellation reaches exactly one row:

```sql
UPDATE workflow_instances
SET cancellation_requested = true, cancellation_reason = $2
WHERE id = $1
```

`engine/store_signals.go:20`, and the MySQL and SQL Server implementations
(`engine/mysql_lifecycle.go`, `engine/mssql_lifecycle.go`) are the same single-row
shape. There is no traversal of `parent_workflow_id` anywhere in the cancellation
path. A cancelled parent's children run to completion, and so do its
grandchildren.

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

Either a decision that cleat's single-row cancellation is correct — in which case
this becomes a deliberate difference like entry 21, and a port test should assert
the children *survive* — or a subtree cancel that skips detached children. The
port cannot pick; both are one test, and they are different tests.
