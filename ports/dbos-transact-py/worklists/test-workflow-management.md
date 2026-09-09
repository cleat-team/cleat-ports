## `tests/test_workflow_management.py` — 46 cases, read at `833794f7`

**This file is mined out. The number that matters is a ceiling, not a backlog:
one case is portable, and porting it means recording a divergence rather than
adding coverage.**

46 cases from 44 `def`s (`test_garbage_collection_batched` is parametrized ×3,
which is the whole of the 44/46 gap — it reconciles README's 46 by an
independent route). 12 are covered. The remaining 34 do not decompose into 34
pieces of work; they bottom out on **six** capabilities cleat does not have,
and two thirds of them were already written down before this survey started.

### Where the 46 go

| bucket | cases | already recorded as |
|---|---:|---|
| garbage collection | 15 | ISSUES 23, route one |
| no delete endpoint | 3 | ISSUES 23, route two |
| `resume_workflow` | 8 | ISSUES 21 |
| enumerate a workflow's readers | 4 | ISSUES 28 |
| `fork_workflow` / restart-from-step | 12 | **not previously recorded** |
| bulk admin over a cohort | 2 | **not previously recorded** |
| asserts on DBOS internals, not the engine | 1 | — |
| **portable** | **1** | filed here as ISSUES 29 |
| | **46** | |

**ISSUES.md already accounted for 30 of the 46 before this survey** — entries 21,
23 and 28, with 23 naming its 13 cases outright. Grepping that file first, as
the `test_queue.py` section recommends, removed two thirds of the apparent job
in one command:

    grep -n "test_workflow_management.py" ports/dbos-transact-py/ISSUES.md

### The two blockers that were not written down

**`fork_workflow` — 12 cases.** Fork restarts a completed or failed workflow from
a chosen step, reusing the recorded results of everything before it. The cases
are not "does fork work"; they are what fork *means* — forking from a failure,
from a named step, from the last step, across an application version change,
with children, with events, with streams. cleat has no counterpart and no
adjacent one: the dispatch in `cmd/cleat-worker/server.go:315-400` offers
`retry`, which re-runs a workflow whole.

Three of the twelve are named `test_restart_fromsteps_*` and one is
`test_fork_from_failure`, which reaches `dbos._sys_db.fork_from_failure` rather
than the public API — so a scan for `DBOS.fork_workflow` finds eleven of twelve
and calls the twelfth something else.

**Bulk admin over a cohort — 2 cases.** `test_bulk_cancel` and
`test_global_timeout` cancel *every* workflow matching a predicate — a set, or
everything started before a cutoff timestamp. cleat cancels one workflow by id.
This is a different shape from the missing-endpoint cases above: the per-item
operation exists and there is no way to ask for it over a cohort.

### The one portable case, and why it is an ISSUES entry

`test_cancel_workflow_children` builds parent → child → grandchild, cancels the
parent, and asserts all three observe it.

cleat's cancellation reaches exactly one row:

    UPDATE workflow_instances
    SET cancellation_requested = true, cancellation_reason = $2
    WHERE id = $1
    -- engine/store_signals.go:20

No traversal, on any of the three dialects. A cancelled parent's children run to
completion.

This is **not** the divergence ISSUES 21 already settles. That entry establishes
that cancellation is cooperative rather than a state transition, and concludes
cleat is right about it. Propagation is a separate axis: a cooperative flag could
perfectly well be set on every descendant and still be cooperative. Filed as
ISSUES 29.

**Corrected 2026-09-09.** This paragraph used to end "It is not, and nothing
recorded that." That is wrong, and entry 29 has been rewritten: cleat *does*
propagate, through `enforceParentClosePolicy`'s `REQUEST_CANCEL` arm, in all
three dialects — measured, a live child is reached about 1.75s after the
cancel. Two things make it easy to miss. The default `parent_close_policy` is
`ABANDON`, so a child gets nothing unless it opted in; and `CancelWorkflow`
itself touches one row, so reading only the cancel path shows no traversal.

What upstream asserts and cleat does not do is **stop the parent**: `AwaitChild`
never checks `PollCancellation`, so a parent blocked on its children finishes on
its own schedule. That is the open question now, and it is narrower than the one
this section originally filed.

### Validation, including where the check was wrong

Every case name announces its own subject, so the classifier can be checked
against the names:

| case | the name announces | classified | |
|---|---|---|---|
| `test_fork_steps` | fork | needs fork | ok |
| `test_delete_workflow` | delete | no delete endpoint | ok |
| `test_get_all_events` | enumeration | ISSUES 28 | ok |
| `test_bulk_resume` | resume | ISSUES 21 | ok |
| `test_payload_garbage_collection` | GC | needs fork | **check wrong** |
| `test_legacy_payload_rows_still_read` | GC (payload retention) | needs fork | **check wrong** |

**The last two are the useful rows, and they are the same defect the
`test_dbos.py` section records one level up.** My classifier tested blockers in
a fixed order with fork first; both cases mention `fork_workflow` incidentally
while being GC cases, so first-match ordering claimed them. The bug is not the
regex — it is that a first-match classifier answers "which blocker did I check
first" while reporting "which blocker applies".

It was caught by reconciling against ISSUES 23's independent count rather than by
the name check: 23 claims **18 of 46** and my buckets gave 16, and two is a small
enough gap to have been rounded away as a judgement difference. Both numbers are
now derived and agree at 18. **A partition that sums correctly is not a partition
that is right** — mine summed to 44/46 in both versions.

### Confidence

The twelve fork cases and the six ISSUES-23 GC cases were classified from the API
each body calls, which is mechanical. `test_cancel_workflow_children`,
`test_global_timeout`, `test_bulk_cancel` and
`test_workflow_outcome_is_owned_by_the_pending_row` were classified by reading
their assertions. The remainder inherit their bucket from ISSUES 21/23/28, which
this survey confirmed by name rather than re-derived.

`test_workflow_outcome_is_owned_by_the_pending_row` is the one case declined as
not-an-engine-assertion: it reaches `dbos._sys_db`, `_active_workflows_set` and
`_serializer` and asserts on DBOS's own bookkeeping.
