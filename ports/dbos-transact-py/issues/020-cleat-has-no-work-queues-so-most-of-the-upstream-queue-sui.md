## 20. cleat has no work queues, so most of the upstream queue suite is unportable

**Class:** Missing API
**Upstream test:** `tests/test_queue.py` — 61 of 91 cases, headed by
`test_one_at_a_time`, `test_one_at_a_time_with_limiter`, `test_limiter`,
`test_dynamic_concurrency_takes_effect`
**Status:** Open

**Filed upstream as cleat#1116** (2026-09-09, session `cleat-5c2b`). The finding
had never reached the engine repo; it exists there now as a question, since
each of these is a plausible design position as well as a plausible gap.

**What upstream asserts**

A DBOS `Queue` carries admission control. Its constructor takes
`concurrency` / `global_concurrency` (cluster-wide cap on workflows running
from that queue), `worker_concurrency` (the same cap per worker process),
`limiter={limit, period}` (at most N *starts* per period), and the three
`partition_*` forms of those. Work enqueued past a limit is **held and
released later** — `test_one_at_a_time` enqueues two workflows and asserts the
second one *runs* once the first finishes.

**What cleat does**

Nothing equivalent — and the first evidence of that is not this investigation.
`tests/test_concurrency.py::test_blocked_task_runs_after_the_holder_finishes`
is **already in the tree, skipped**, docstringed as the second half of upstream
`test_one_at_a_time_with_worker_concurrency`:

> Left in place, skipped, rather than omitted: an absent test is
> indistinguishable from an untried one, and this is the assertion a reader
> comparing the two systems will look for first.

Someone tried the deferral assertion, found it could not pass, and left a
marker instead of a claim. Everything below is the mechanism behind that
result, arrived at separately and agreeing with it.

The nearest-looking feature is a different one. `ConcurrencyKey` is a
**distributed mutex, not a semaphore**.
`concurrency_keys.key_hash` is the PRIMARY KEY (`migrations/postgres/001_schema.sql:345`)
and the acquire is

    INSERT INTO concurrency_keys (...) VALUES (...)
    ON CONFLICT (key_hash) DO NOTHING RETURNING workflow_id   -- engine/db.go:766

One row per key means exactly one holder. There is no count column and no `n`
parameter on the path; the schema cannot represent "let 5 run".

It also **rejects rather than defers**. On the HTTP start path
(`cmd/cleat-worker/server.go:619-670`) a losing `Cleat-Concurrency-Key` start is
**terminated and answered 409**. The work is destroyed, not queued. This is the
fact that makes the suite unportable rather than merely unwritten: a ported
`test_one_at_a_time` needs the second enqueue to eventually run, and in cleat
there is nothing left to run.

**And there is no deferral in the guest API either**, which is the third
independent place the control is absent. `AcquireConcurrencyKey` returns a
**bool, immediately** -- `packAcquireLockResult(acquired, 0)`,
`engine/locking.go:62-79`. It does not suspend, does not retry, does not queue;
the guest gets `false` and must decide what to do.

So: no slot count in the schema, no deferral at the front door, no suspend in
the guest API. Taken together the gap is **architectural rather than a missing
feature** -- adding a semaphore to the schema would still not make
`test_blocked_task_runs_after_the_holder_finishes` pass, because the guest has
no way to wait. That would need an ABI change.

Enforcement is HTTP-only. From the comment at `server.go:640`:

> The HTTP layer is the only enforcement point for Cleat-Concurrency-Key;
> ClaimWorkflows does not consult concurrency_keys.

So child workflows, redrive, and any internal start path walk past it. The
guarantee is a property of one handler, not of the engine.

Two adjacent features are easy to mistake for the missing one:

- `task_queue` (on `workflow_instances` and `workflow_defs`, filtered in the
  claim CTE at `engine/store_lifecycle.go:105`, selected by `--task-queue`) is
  **routing/affinity only**. There is no queue-config table — `grep 'CREATE
  TABLE.*queue' migrations/postgres/*.sql` returns nothing — so no limit can
  attach to a queue name. `QueueDepth` is one global backlog gauge.
- `--max-quota-concurrency-keys` counts keys held **by a single workflow**
  (`GetConcurrencyKeyCount(ctx, s.workflowID)`, `engine/locking.go:30-46`). It
  is a per-workflow leak quota, not a limit on concurrent work.

| DBOS control | cleat | Verdict |
|---|---|---|
| `worker_concurrency` | `--concurrency`, per **process**, all queues | Partial — wrong granularity |
| `global_concurrency` | nothing | None — effective cap is `--concurrency` × workers, uncoordinated |
| `concurrency` (queue-level) | `ConcurrencyKey`: N=1, rejects | None |
| `limiter {limit, period}` | nothing | None — `--rate-limit*` is per-IP/per-tenant **HTTP request admission** |
| `partition_*` (3 controls) | nothing | None — no partition concept |
| priority ordering | `priority` column, `ORDER BY priority ASC, created_at` | Yes |
| dedup / idempotency | `Idempotency-Key` → `idempotency_keys` | Yes |
| named queue | `task_queue` | Partial — routing only |

**Assessment**

Missing API rather than Bug or Design difference. Nothing here misbehaves; the
feature is absent. Calling it a design difference would be the comfortable
answer, and the skipped test above is what rules it out: a deliberate design
difference does not leave an assertion in the tree that its author expected to
pass.

The framing that holds: cleat has **task queues** (routing) and **locks**
(mutual exclusion) but no **work queues** (admission control with deferral),
and DBOS's queue suite is almost entirely about the third.

The 45 blocked cases should not be written. They would fail for "cleat has no
queues", which is a feature request, not something a test should pin. The
32 portable cases are tracked in the README table; 10 are done.
