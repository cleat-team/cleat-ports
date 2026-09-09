## 30. A run records when it was created and when it finished, never when it started

**Class:** Missing API
**Upstream test:** `tests/test_queue.py` — `test_simple_queue`
**Status:** Open

**What upstream asserts**

`test_simple_queue` finishes on two timestamp assertions, and they are the only
part of that case cleat has no answer for:

```python
assert status.dequeued_at and status.created_at
# Both are database-stamped, so a second-resolution clock can land the
# enqueue and its dequeue on one tick.
assert status.dequeued_at >= status.created_at
```

The upstream comment is doing real work: it explains why the comparison is `>=`
rather than `>`, which tells you the assertion is about ordering of two
independently stamped events rather than about elapsed time.

**What cleat does**

`workflow_instances` carries `created_at` and `completed_at` and nothing
between them. The full set of time-like columns is `heartbeat_at`,
`next_wake_at`, `created_at`, `completed_at`, `compacted_at`, and none of the
first three is a start:

- `heartbeat_at` is rewritten continuously by the owning worker, so it is the
  *latest* sign of life, not the first.
- `next_wake_at` is a schedule for the future.
- `compacted_at` belongs to event compaction.

A search across the schema for a claim-time column finds nothing:

```
column_name ~ 'start|claim|dequeue|first_run'  ->  workflow_instances.reclaim_count
```

which is a counter, not a time.

**Why this is worth an entry rather than a shrug**

Three quantities every queueing system is asked about are unavailable, and they
are unavailable for one reason:

| question | needs | cleat has |
|---|---|---|
| how long did work wait before it ran? | start − created | — |
| how long did the work itself take? | completed − start | — |
| is the backlog draining or growing? | start times over a window | — |

`completed_at - created_at` measures wait **plus** execution, so a run that sat
in a backlog for a minute and a run that executed for a minute are the same
number. That is the one distinction an operator watching a queue needs, and it
is exactly the distinction the pair collapses.

It also is not recoverable from event history: the first event's timestamp is
the first *step*, and a workflow whose body begins with a durable sleep or
whose first act is a host call records nothing at claim time.

**Not portable, and it is the whole of what is left in `test_simple_queue`**

The rest of that case — the workflow runs once, its step runs once, a re-invoke
under the same id does not re-run the body — is covered by
`test_queues.py::test_the_same_idempotency_key_starts_one_run` and
`test_a_completed_run_still_answers_for_its_idempotency_key`. The timestamps
are the residue, and there is no proxy for them that would not be inventing a
measurement cleat does not take. See WORKLIST.md, `tests/test_queue.py`.
