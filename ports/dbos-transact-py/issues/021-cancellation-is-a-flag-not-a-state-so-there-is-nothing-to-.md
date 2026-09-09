## 21. Cancellation is a flag, not a state — so there is nothing to resume

**Class:** Deliberate difference (with one open question)
**Upstream test:** `tests/test_workflow_management.py` — the `resume_workflow` cases
**Status:** Closed — a divergence cleat is right about, not a defect. One
adjacent question (reprocess semantics) deliberately deferred; see below.

**What upstream asserts**

DBOS's `cancel_workflow` "sets its status to `CANCELLED`, removes it from its
queue and preempts its execution (interrupting it at the beginning of its next
step)". `resume_workflow` then "immediately starts it from its last completed
step", and the documentation is explicit that this covers "workflows that are
cancelled **or have exceeded their maximum recovery attempts**".

**What cleat does**

Cancellation is **cooperative and is not a state transition**. `POST
/api/workflows/:id/cancel` runs

    UPDATE workflow_instances SET cancellation_requested = 1, cancellation_reason = ?

and nothing else. A workflow observes it by calling `h.PollCancellation()` and
decides what to do; one that never asks runs to completion, and the endpoint
answers 200 either way. There is no `cancelled` status — the engine writes
`ready`, `running`, `done`, `failed`, `terminated`, `terminating` and
`dead_lettered`. A workflow that observed its cancellation and returned ends in
`done`, the same status as one that succeeded.

Both facts are already pinned by `tests/test_cancellation.py`.

**Assessment: this is a deliberate difference and cleat has the better of it.**

`resume` is not an endpoint cleat is missing. It is an operation with **no state
to act on**: there is no paused run to restart, so adding `/resume` would close
nothing.

And resume-after-cancel is not merely unnecessary here, it is **unsound in the
presence of compensations**. If a saga is cancelled at step 5 and its
compensations run, the history records step 5 as completed while the world has
had it undone. "Start from the last completed step" then resumes into a state
that has been compensated away. cleat's saga port exists because compensation is
a first-class pattern, so this is not a hypothetical.

A weaker but real second reason: if cancel is reversible, an operator can never
say "I stopped it", only "I stopped it for now".

**The open question is somewhere else, and it is worth deciding on the record.**

DBOS puts two operations behind one verb, and only one of them is about cancel.
The other — resuming work that **exceeded its recovery attempts** — is cleat's
dead-letter queue, where the *system* gave up rather than an operator, and none
of the objections above apply.

cleat has that re-drive, and `test_reprocessing_starts_a_new_run_and_leaves_the_original`
pins its shape: reprocess creates a **fresh run** with a new id and leaves the
original `dead_lettered`. So a workflow that dead-lettered at step 9 of 10
repeats eight steps of completed durable work. Where those steps are a payment,
a transfer or an expensive model call, that is the cost that matters.

**What makes this a real question rather than a feature request: cleat already
does checkpoint resumption.** It is exactly what recovery after a worker crash
is, and `tests/test_recovery.py::test_a_workflow_survives_the_loss_of_its_worker`
asserts that the pre-crash durable call is *not* repeated. The machinery exists
and is tested. Reprocess-from-scratch is a choice, not a limitation.

**Deliberately deferred (2026-09-08), and the deferral is the decision.** Either
answer is defensible — from-scratch is safer if a step's side effect might be
half-applied, from-checkpoint is cheaper and uses a guarantee cleat already
makes — and there is currently no evidence about which case actually arises.
Choosing now would be picking on aesthetics.

What is recorded here is that the current behaviour is a **choice**, not a
limitation, so nobody re-derives it as a defect. Revisit when there is
information the reading cannot supply:

  - a workflow that dead-letters late in an expensive chain, where the cost of
    repeating completed steps is real rather than theoretical
  - a case where reprocess-from-scratch *causes* a problem — a step whose side
    effect is not safely repeatable being redone on re-drive
  - an operator asking for it

Until one of those, from-scratch stands. The point of this entry is that the
next person meets a documented decision rather than an accident.

**The rest of the surface, for completeness**

| DBOS | cleat | verdict |
|---|---|---|
| `cancel_workflow` | `POST /cancel` | present, different semantics (above) |
| `resume_workflow` | nothing | no state to resume; see above |
| `fork_workflow` (new id, start from step N) | nothing | absent, low priority — an operator patching tool that does not touch the durability contract |
| `delete_workflow` | nothing | absent. Retention purges exist internally (`deleteCompletedWorkflowsBatch`) but no API reaches them |
| `list_workflows` | `GET /api/workflows` | present |
| `list_workflow_steps` | `GET /:id/history` | present |
| `update_workflow_attributes` | **not** `/:id/update` | **name collision, not a counterpart.** DBOS replaces a searchable custom-attributes dictionary. cleat's `/update` is a Temporal-style workflow *update* (`poll_update` / `complete_update`) — an entirely different mechanism that maps cleanly on a grep and not at all in behaviour |

Two corrections to earlier notes, recorded so they are not repeated: **DBOS has
no `restart_workflow` and no `pause_workflow`.** Neither appears in the Python
API or in `DBOSClient`. This port's README described `test_workflow_management.py`
as covering "cancel, resume, fork, list, restart"; the last of those does not
exist.

Method: the cleat column is read from the route dispatch in
`cmd/cleat-worker/server.go:297-470`, which is the only place routing happens —
not from grep, which has already missed a column in this repo once. The DBOS
column is from the published API reference rather than from memory or source.

**Two upstream races this decision forecloses, found while classifying the file**

Recorded here because both are engine-level correctness cases, and reading them
turns #21 from "cleat lacks a feature" into "cleat's model removes a class of
bug". That is a stronger claim and it should not be left implicit.

`test_active_id_released_before_outcome_write` asserts that an executor's
active-workflow-ID entry is released *before* the terminal outcome write becomes
durable. Its own comment gives the failure it prevents:

> run 1's stale write is in flight, a client observes CANCELLED and resumes,
> this same executor dequeues the resumed workflow, but the dispatch finds the
> stale active-ID entry, takes the non-owner path, and waits forever on a row
> nobody is executing.

Every step of that needs a resume. cleat has no cancelled state and no resume,
so the sequence cannot begin. **Unportable because the bug is unreachable**, not
because a control is missing — the opposite of #20's case.

`test_workflow_outcome_is_owned_by_the_pending_row` asserts a run may record its
outcome only while its status row is still `PENDING`; any other status means the
run lost ownership and the recorded outcome wins over the one the run computed.
Upstream lists four ways ownership is lost, and two of them — a recovery race
and dead-lettering — exist in cleat, so the property survives the reduction.

**cleat's answer is stronger than the property upstream tests.** The outcome
write is fenced on both owner and generation, on all three dialects
(`engine/store_lifecycle.go:382`, `engine/mysql_lifecycle.go:419`,
`engine/mssql_lifecycle.go:599`):

    UPDATE workflow_instances
    SET status = 'done', ...
    WHERE id = $1 AND assigned_to = $2 AND generation = $5

Zero rows affected returns `ErrFenceLost` and **rolls back rather than
commits**, with a comment giving the reason: the idempotency-key write and the
post-commit cleanup below it are not safe to run on the new owner's behalf. A
status check answers "is this run still current"; a generation fence answers it
without a window between the check and the write.

**Not portable in this harness, and that is a harness limit rather than a
verdict.** Provoking it needs a stale-but-living run: worker A stalls, the
reaper reassigns, worker B completes, then A wakes and writes. The port harness
runs exactly one worker and **that worker is the API server** — see
`conftest.py`'s `worker.stop()` — so freezing A freezes the API and nothing can
be observed during the outage. A second worker sharing the database would unlock
this and the cross-worker cases generally; it is the highest-value harness change
available and is not attempted here.
