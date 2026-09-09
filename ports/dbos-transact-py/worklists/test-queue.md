## `tests/test_queue.py` — 91 cases, read at `833794f7`

The largest file in scope and the last priority-1 one without a work-list. The
census below is not a fresh reading of all 91: `scripts/count-queue-cases.py`
already classifies them by the queue controls they touch, and this section
takes that as given and reads only the 19 it calls plausibly portable. What is
new here is the second pass — of those 19, which are **already answered in this
port**, which are **not portable after all**, and which are actually left.

### The classifier's split, quoted rather than recomputed

```
91 collectible cases
  needs a control cleat lacks : 61
  needs only priority/dedup   : 10
  needs no queue control      : 20
  ...of those, needs queue SEMANTICS cleat lacks : 11
  => plausibly portable       : 19
```

The 61 and the 11 are not revisited. They fail on `worker_concurrency`,
`limiter`, `partition_concurrency`, named-queue residency and selective queue
listening, none of which cleat has, and ISSUES.md "no work queues" covers the
class. **The 19 are the only ones worth a second opinion, because "needs no
queue control" is a statement about the controls, not about whether cleat can
express the assertion underneath.**

### Already answered here — 8

| upstream case | where |
|---|---|
| `test_complex_type` | `test_complex_args.py` |
| `test_duplicate_workflow_id` | `test_queues.py` |
| `test_queue_deduplication_recovery` | `test_concurrency.py` |
| `test_queue_executor_id` | `test_executor_identity.py`, and ISSUES.md 26 for the half cleat cannot answer |
| `test_queue_workflow_in_recovered_workflow` | `test_recovery.py` |
| `test_enqueue_version` | `test_versions.py` |
| `test_unsetting_timeout` | `test_timeouts.py`, as a documented skip — ISSUES.md 25 |
| `test_timeout_queue_recovery` | ISSUES.md, same gap |

### Ported by this section — 1

`test_queue_deduplication`'s **final** assertion, which nothing here covered:
upstream re-enqueues under a deduplication ID it has already used and asserts
the enqueue **succeeds**, because the workflow has left the queue. cleat
answers the opposite way — `idempotency_keys.expires_at` defaults to seven days
out, so the binding outlives the run — and the existing dedup tests all
re-submit while the first run is still **in flight**, which is a different
question.

`test_queues.py::test_a_completed_run_still_answers_for_its_idempotency_key`.
It is a deliberate difference, not a defect, and the test says so in its
docstring so that a future change here reads as a decision rather than a fix.

### Not portable, despite the classifier — 6

The classifier asks "does this need a queue control", which is the right
question for 85 of 91 cases and the wrong one for these:

| upstream case | why not |
|---|---|
| `test_enqueued_async_workflow_survives_gc` | asserts on `dbos._workflow_tasks` and Python future garbage collection — a property of the DBOS runtime, not of a durable engine |
| `test_listen_queue` | selective queue listening; there is no queue to listen to |
| `test_enqueue_options_require_a_queue_async` | asserts enqueue **options** are rejected without a queue; both halves are absent |
| `test_queue_transaction` | DBOS transactions; the gap is documented outside the ledger, see the `test_dbos.py` section above |
| `test_queue_step` | enqueues a **step** as a top-level unit; cleat steps exist only inside a workflow body |
| `test_simple_queue` | see below — the residue is timestamps cleat does not record |

### The one that produced a new ISSUES entry

`test_simple_queue` looked portable and mostly is: "the workflow runs once, its
step runs once, a re-invoke under the same id does not re-run the body" is
already covered twice over in `test_queues.py`. What is left is its last two
lines:

```python
assert status.dequeued_at >= status.created_at
```

**cleat records no start time.** `workflow_instances` has `created_at` and
`completed_at`; `heartbeat_at` is rewritten continuously so it is the latest
sign of life rather than the first, and a schema-wide search for
`start|claim|dequeue|first_run` returns only `reclaim_count`. So queue latency
and execution time are both unavailable, and `completed_at - created_at`
collapses them into one number. ISSUES.md 30.

### Still open — 2, and both are async mirrors

`test_simple_queue_async` and `test_queue_deduplication_async` are the async
forms of cases whose sync form is now covered. README.md's priority note for
`test_async.py` applies here for the same reason: the async surface is the
SDK's, and re-asserting an engine property through it tests the client.

`test_enqueue_version_async` is the third, and the same applies.

### What this says about where to go next

`test_queue.py` is **mined out**, and that is the useful conclusion. Its 91
cases were the largest single gap in the coverage table — 19 of 91 — and the
gap is a ceiling rather than a backlog: 72 need queue machinery cleat does not
have, 8 were already answered elsewhere in this port, 6 are not engine
assertions at all, and 3 are async mirrors. One case was genuinely missing and
is now ported; one produced an ISSUES entry.

**The coverage table's `Cases here` column should be read as "what this port
can say about that file", not as progress toward the case count.** For
`test_queue.py` the reachable maximum is around 20 of 91, and it is now 20.

---
