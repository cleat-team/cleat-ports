## 26. Nothing records which worker ran a completed workflow

**Class:** Missing API
**Upstream test:** `tests/test_queue.py` — `test_queue_executor_id`
**Status:** Open

**What upstream asserts**

`executor_id` is a durable property of a run. Upstream sets one, runs a
workflow, then changes the executor id and starts the same workflow id again:

```python
assert handle.get_status().executor_id == original_executor_id
GlobalParams.executor_id = new_executor_id
with SetWorkflowID(wfid):
    handle = DBOS.enqueue_workflow('test-queue', example_workflow)
assert handle.get_status().executor_id == original_executor_id
```

The second read is the assertion: a completed run still names the executor that
*originally* ran it, and a later start under the same id does not overwrite it.

**What cleat does**

`workflow_instances.assigned_to` is exposed on the API's run record, and it is
a **lease**, not an audit field. `finalize_workflow_status` clears it on every
terminal branch while fencing the write on it:

```sql
UPDATE workflow_instances
SET status = 'done',
    ...
    assigned_to = NULL
WHERE id = p_workflow_id
  AND assigned_to = p_worker_id      -- the fence
  AND generation = p_generation;
```

The worker identity authorises the terminal write and is erased by the same
statement. So the field that would say which worker ran the workflow is the
fence for the write that removes it.

Measured on a ports database of 185 terminal runs: `assigned_to` is blank on
**185 of 185** across `done`, `failed`, `terminated` and `dead_lettered`.

**Scope: all three dialects.** `assigned_to = NULL` appears three times — once
per terminal branch — in the authoritative procedure for each of
`migrations/postgres/050`, `migrations/mysql/049` and `migrations/mssql/053`.
This is not a PostgreSQL-only behaviour.

**The second column, and why it does not close this**

`sticky_worker_id` is blank on all 185 rows too, and that is **not** evidence
it is cleared at finalize: sticky routing is opt-in and this suite never
exercises it, so the sample alone cannot distinguish "cleared" from "never
set". Resolved by reading the writes rather than the rows — it is durably
written (`UPDATE workflow_instances SET sticky_worker_id = $2`) and explicitly
cleared by `ClearStickyWorker`, so blank here means never set.

That narrows this entry's wording without closing it. `sticky_worker_id` says
which worker a workflow **must run on**, not which one **ran** it, and it
exists only for workflows that opted into sticky routing. A routing constraint
that names a worker is not an execution record: it is set before the run by
whoever pinned it, survives independently of what actually executed, and can be
removed while the history it would explain remains.

So the accurate claim is the narrower one: **no field records which worker
executed a completed run.** `assigned_to` could and is erased;
`sticky_worker_id` answers a different question and is usually absent.

**Why it matters beyond conformance**

"Which worker ran this?" is a routine operational question for a failed or slow
run, and cleat cannot answer it after the fact for any run that reached a
terminal state. Every run that is interesting to ask about is one that has
finished.

**Tests**

`tests/test_executor_identity.py`, skipped: the assertion needs a durable
executor field to read, and there is none to read.

---
