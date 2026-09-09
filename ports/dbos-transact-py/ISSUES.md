# dbos-transact-py: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

Empty is the correct starting state. Add entries as you port, not at the end.

**This file was backfilled on 2026-09-07, and that was a mistake worth naming.**
Nineteen findings were recorded straight onto core issues and PRs while this
file stayed empty, so for two days the port's own answer to "what has this
already found?" was "nothing". Every entry below was reconstructed after the
fact from the core tracker, which is why several say less about the upstream
assertion than they would have if written at the time. Add entries as you port.

---

## Template for an entry

## N. <one-line summary>

**Class:** Bug | Missing API | Design difference
**Upstream test:** `<file>::<test name>`
**Status:** Open | Promoted (cleat-team/cleat#NNN, YYYY-MM-DD) | Won't fix

**What upstream asserts**

<The guarantee the upstream test pins down, in plain language. Describe the
behaviour — do not paste upstream code.>

**What cleat does**

<Observed behaviour, with the minimal reproduction.>

**Assessment**

<Why this is a bug / missing API / deliberate difference. If it is a deliberate
difference, say why the difference is deliberate — that is the comfortable
answer, so it needs the most support.>

---

# Findings

Nineteen to date. Fourteen are fixed and merged, five are open.

Class is `Bug` unless stated. "Promoted" here means a regression test that gates
merges in `cleat-team/cleat`, in the package it guards — see step 4 of
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

## 1. Seven API routes were registered on a table the binary never used

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#830, 2026-09-06)
**Upstream area:** `test_workflow_management.py` — list, cancel, resume

Two route tables existed; the worker served one and seven instance and admin
routes were registered on the other. The endpoints answered the SPA's HTML
fallback rather than 404, so a client saw a 200 with a web page.

## 2. An admin API refusal answered 500

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#832, 2026-09-06)
**Upstream area:** `test_workflow_management.py`

The HTTP status was derived from the error *message* by substring, so a refusal
that should have been 400/404/409 came back 500. Now classified with
`errors.Is` against explicit sentinel classes.

## 3. Three host calls dropped work past the end of replay history

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#835, 2026-09-06)
**Upstream area:** `test_dbos.py` — steps after recovery

`DurableSend`, `DurableScheduleInvoke` and streaming plugin calls returned
success without doing anything when the step index ran past recorded history.
The replay branch never called `exitReplay()`, so genuinely new work took the
replay path and was silently discarded.

## 4. `cleat vet` accepted an entry point taking a single string

**Class:** Missing API · **Status:** Promoted (cleat-team/cleat#839, 2026-09-06)
**Upstream area:** none — found while porting, in the port's own workflows

A workflow with exactly one string parameter receives the raw input JSON rather
than a named field. That is a rule, not a defect, but nothing warned about it
and it silently produced a key that was a JSON object. Now W003.

## 5. A suspending segment discarded the query state it was carrying

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#844, 2026-09-06)
**Upstream area:** `test_dbos.py` — workflow status while running

Query state set before a suspension was lost, so a reader polling a suspended
workflow saw nothing. Covered by `test_query_state.py`.

## 6. A completing child rewrote its parent's event and left the checksum stale

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#846, 2026-09-06)
**Upstream area:** `test_dbos.py` — child workflows

The child wrote its result into the parent's recorded `await_child` event
without recomputing the chained checksum, so the parent failed its next segment
with a checksum mismatch. Covered by
`test_children.py::test_awaiting_one_child_survives_the_parent_suspending`.

## 7. `ParentClosePolicy TERMINATE` did not terminate a child a worker held

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#848, 2026-09-07)
**Upstream area:** `test_dbos.py` — child lifecycle

The TERMINATE arm marked the row failed but left `assigned_to` set and the
generation unchanged, so the worker holding the child kept running it.

## 8. A zero `MaxInterval` meant "a maximum of zero"

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#850, 2026-09-07)
**Upstream area:** `test_failures.py` — retry policy

An unset `MaxInterval` clamped every backoff to zero rather than meaning "no
maximum", so retries hammered with no delay.

## 9. `deploy-workflow` ignored the version embedded in the WASM

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#861, 2026-09-07)
**Upstream area:** none — found standing up the multi-dialect harness

It auto-incremented unconditionally, so redeploying changed bytes wrote a
version the binary did not report, and the engine's run-time version check
rejected it.

## 10. A policy-terminated child recorded no `completed_at`

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#864, 2026-09-07)
**Upstream area:** `test_dbos.py` — child lifecycle

Every retention sweep gates on `completed_at IS NOT NULL`, so those rows were
uncollectable. Rows written before the fix stay exempt — cleat-team/cleat#867.

## 11. API key creation emitted PostgreSQL SQL to every dialect

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#865, 2026-09-07)
**Upstream area:** none — found running the suite on MySQL and SQL Server

`INSERT INTO admin.tenant_api_keys ... VALUES ($1, ...)` unconditionally. MySQL
has no `admin` schema and read it as a database: `Unknown database 'admin'`.

## 12. On MySQL, API keys are written to one database and read from another

**Class:** Bug · **Status:** Open (cleat-team/cleat#866, PR #884)
**Upstream area:** none — found running the suite on MySQL

MySQL isolates tenants by database, and the key lookup ran on a tenant-scoped
store while every writer used the base database. `--require-auth` defaults on,
so the HTTP API answered 401 to every request with no key that could work. The
suite failed 40 of 44 on MySQL for this alone.

## 13. A workflow whose only host call was `PluginCallStreaming` did not compile

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#875, 2026-09-07)
**Upstream area:** none — found writing the first streaming-plugin coverage

The generated adapter used `unsafe` without importing it. Any second host call
pulled the import in, so the defect needed a workflow using that call and
nothing else. Nothing in the tree was shaped that way.

## 14. The streaming plugin registry was built, filled, and never given to the engine

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#879, 2026-09-07)
**Upstream area:** none — found writing the first streaming-plugin coverage

Every streaming plugin call answered `no plugin stream registry configured`.
`WithPluginStreamRegistry` had seven references, all in `engine/unit_test.go`,
where the test supplies the option itself and so cannot see that nothing else
does. Same shape as cleat-team/cleat#769.

## 15. `PollChild` is not replayed

**Class:** Bug · **Status:** Open (cleat-team/cleat#847, PR #871)
**Upstream area:** `test_dbos.py` — child status polling

It re-queries the child live on every execution, so a poll that answered
"running" before a suspension can answer "completed" after it. Resolution:
derive the answer from the parent's durable clock and the child's
`completed_at` rather than recording an event — the rule is that the answer
must be a function of recorded state, not that everything records an event.

## 16. `PollSignal` is not replayed

**Class:** Bug · **Status:** Open (cleat-team/cleat#882)
**Upstream test:** `test_dbos.py` — `recv` without blocking
**Port test:** `test_signals.py::test_polling_finds_nothing_before_a_signal_and_finds_it_after`, skipped naming the issue

Same shape as #15, for signals. The first poll re-answers `true` after a
suspension, carrying a payload that did not exist when that line ran. A sweep of
all 50 host-call entry points found exactly these two lacking replay handling,
so the family is closed at two.

## 17. A continue-as-new chain is unfollowable

**Class:** Bug · **Status:** Open (cleat-team/cleat#826; recording half in PR #886, retrieval in #887)
**Upstream test:** `test_dbos.py` — continue-as-new

The caller polls the id it started, sees `done` and `{}`, and the run carrying
the real result is unnamed. Upstream keeps the workflow id across the
transition; cleat inserted a fresh uuid with nothing linking the two.

A second defect had to be fixed before this was even reachable: the old run's
result was written raw into a JSON column, so every continuation died with
`22P02`.

## 18. Workflow updates are accepted with a 202 and never delivered

**Class:** Missing API · **Status:** Open (cleat-team/cleat#849; implemented across five SDKs)
**Upstream area:** `test_dbos.py` — interacting with a running workflow

Filed as a scheduling bug. It was not: no worker configured an update handler
and no guest exported one, so the feature was unimplemented rather than
misrouted. The original "deliver at a segment boundary" recommendation would
have turned a silent hang into a silent rejection.

## 19. `DurableCallWithHeartbeat`'s `onProgress` could never fire

**Class:** Design difference, resolved as removal · **Status:** Promoted (cleat-team/cleat#854, PR #881, 2026-09-07)
**Upstream area:** `test_failures.py` — long-running step heartbeats

The WIT interface's `durable-call-heartbeat` takes four parameters and never had
a progress channel, so the SDKs exposed a callback the ABI cannot deliver. Inert
in compiled workflows, `localdev` and `cleattest` alike. Removed rather than
wired: the guest is suspended inside the import for the whole call, so there is
no moment at which the host could run guest code.

## 20. cleat has no work queues, so most of the upstream queue suite is unportable

**Class:** Missing API
**Upstream test:** `tests/test_queue.py` — 61 of 91 cases, headed by
`test_one_at_a_time`, `test_one_at_a_time_with_limiter`, `test_limiter`,
`test_dynamic_concurrency_takes_effect`
**Status:** Open

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

## 22. Concurrent steps inside a workflow are refused by the determinism analyzer

**Class:** Deliberate difference
**Upstream test:** `tests/test_concurrency.py` — 9 of 11 cases, headed by
`test_high_async_concurrency`, `test_gather_manysteps`,
`test_gather_distinct_steps_deterministic_order`
**Status:** Closed — unportable in principle, not pending a fix

**Count first, because the inventory is wrong about this file too.** The README
listed 21 cases. Counted by collection at the pin it is **11**; the 21 is the
`grep '^def test_'` figure, the same inflation corrected for `test_queue.py` in
#20. Re-derive with `scripts/count-queue-cases.py`.

**What upstream asserts**

Nine of the eleven are `async def`, most using `asyncio.gather`. They exercise
the Python SDK's async model — several steps of **one** workflow running
concurrently, streams written from concurrent tasks, event set/get under load,
and thread starvation during recovery:

    test_gather_manythings                                 events, streams
    test_gather_manysteps
    test_gather_many_send_async
    test_gather_many_write_stream
    test_gather_many_write_stream_from_step                streams
    test_gather_many_set_event                             events
    test_high_async_concurrency                            asyncio.gather
    test_async_recovery_direct_child_no_thread_starvation  asyncio.gather, recovery
    test_gather_distinct_steps_deterministic_order         asyncio.gather

The remaining two (`test_concurrent_workflows`, `test_concurrent_getevent`) are
synchronous and use threads to drive **separate** workflows. Those look
portable — starting N workflows and asserting all complete is something cleat
does — and are the work-list for this file.

**What cleat does: refuses the constructs at build time.**

Not "does not support" — the analyzer rejects the whole family, syntactically
and before anything runs (`internal/closure/closure.go`):

| code | construct | site |
|---|---|---|
| **E001** | `go` statement | `:275` |
| **E002** | channel send | `:288`, `:308` |
| **E012** | `close()` | `:386` |
| **E013** | `sync.{Mutex, RWMutex, WaitGroup, Once, Cond, Pool, Map}` | `:412` |
| **E013** | calls on a sync-typed variable, e.g. `mu.Lock()` | `:441` |

That last row matters: the ban catches `mu.Lock()` where `mu` is a
`sync.Mutex` variable, not merely the written-out selector, so it is not
evadable by ordinary indirection.

**Assessment**

A DBOS workflow may `asyncio.gather` its steps. **A cleat workflow may not run
anything concurrently at all, by design.** E001's own message states the reason:

> goroutines introduce non-deterministic scheduling across replays

So these cases are not unportable because a control is missing. They are
unportable because **no implementation that preserves replay determinism could
pass them.** That distinction is the whole entry: "cleat lacks a control"
invites someone to add the control, and here there is nothing to add.

Already pinned by `ports/samples-go/tests/nondeterminism_test.go`
(`TestForbiddenConstructsAreRefusedAtBuildTime`), the port of upstream
`goroutine/` and `mutex/`, which records the same refusal from the other
direction.

**Note the near-miss, because it is the useful part.**

This file was first assessed against #20's criterion — `ConcurrencyKey` is a
mutex not a semaphore, so bounded parallelism is unrepresentable. That criterion
is **correct and is the wrong instrument here**: it would have bucketed all nine
async cases as "needs a control cleat lacks", which is true of the queue file
and false of this one.

The conclusion would have been right — the cases are unportable — with the
reason wrong. **Nothing downstream would have contradicted it**, because the
tests really do fail and the entry really would have explained why. A correct
conclusion with a wrong reason survives every check that only looks at the
conclusion.

What caught it was counting the cases and reading what they exercise, rather
than applying the criterion that had just worked on the neighbouring file.

**Method:** the cleat column is read from `internal/closure/closure.go` with line
numbers, verified independently by a second session. The upstream column is
collected and characterised by AST from the pinned commit — names and constructs,
**not bodies** — so the 2-portable / 9-unportable split is directional rather
than exact.

This almost certainly covers much of `tests/test_async.py` (57 by the old count,
uncounted by collection, 0 ported), which nobody has assessed. Same question,
larger file.

## 23. Nothing can ask cleat to remove a workflow record

**Class:** Defect — filed as cleat#1002
**Upstream test:** `tests/test_workflow_management.py` — 18 of 46 cases, headed by
`test_garbage_collection`, `test_payload_garbage_collection`,
`test_delete_workflow`
**Status:** Open — unportable until cleat#1002 lands, then portable

**18 of 46 cases in this file bottom out on one missing capability**, arriving by
two different routes. Both are recorded here rather than separately because a fix
for either is most of a fix for the other.

**Route one: garbage collection (15 cases).**

DBOS exposes GC as a **callable API** taking a cutoff timestamp and a row
threshold, so a test creates rows, calls GC with a cutoff a millisecond in the
past, and asserts what survived:

    test_garbage_collection                                    the base case
    test_garbage_collection_batched                            parametrized x3
    test_garbage_collection_batched_rows_threshold
    test_garbage_collection_batched_resumable
    test_garbage_collection_batch_size_validation
    test_garbage_collection_collects_rows_that_terminalize_mid_sweep
    test_garbage_collection_spans_every_application
    test_payload_garbage_collection
    test_payload_gc_spares_a_straggler_then_reclaims_it
    test_payload_gc_never_orphans_a_status_row
    test_payloads_survive_while_their_status_row_does
    test_legacy_payload_rows_still_read
    test_retention_lock_key_is_the_cross_sdk_contract

The interesting ones are not "does it delete". They are the **ordering and
partial-failure** cases: a row reaching a terminal state *during* a sweep, a
sweep interrupted and resumed, and payload rows that must never outlive — or
predecease — the status row they belong to.

cleat has the feature and no way to invoke it. `--retention-days` defaults to
**30 and is on by default** (`cmd/cleat-worker/config.go:107`); a second sweep,
`--completed-workflow-retention-days`, defaults to 0 and is opt-in. Both run from
`retentionLoop` (`cmd/cleat-worker/setup.go:2482`) on a **hardcoded 24-hour
ticker with no sweep at startup**, so a worker restarting inside a day never
executes either. The cutoff is computed at day granularity, so no sub-day window
can be requested even in principle.

**This is a defect, and it took checking to be sure of that.** Every background
loop in the worker is tick-first; none pre-runs its sweep. The distinguishing
fact is the interval, not the pattern — the next-longest loop is
`memoryCleanupLoop` at 10 minutes, and retention is 144x that. Tick-first costs
the other seven one period of latency. It costs retention the entire feature on
any worker with a lifetime under a day. Full loop table in cleat#1002.

**Route two: there is no delete endpoint (3 cases).**

    test_delete_workflow
    test_bulk_delete
    test_client_delete_workflow

`DELETE` appears in exactly three places in the worker's API, and none of them
removes a workflow:

| route | what it deletes |
|---|---|
| `DELETE /api/workflows/{def}/routing/{k}` | a routing rule (`server.go:366`) |
| `DELETE /api/workflows/{def}/tags/{k}` | a tag (`server.go:375`) |
| `DELETE /api/schedules/{name}` | a schedule (`server.go:1665`) |

The instance surface is read-only apart from lifecycle: `/api/instances/{id}`,
`/api/instances/{id}/events`, `/api/instances/{id}/state`, all `GET`
(`api_instances.go:28-32`). The admin surface is `force-complete`, `force-fail`,
`re-replay` and `steps/{n}/resolve`, all `POST` (`api_admin.go:41-47`). So the
only mechanism in cleat that removes a workflow record at all is the retention
sweep — which is route one.

**Read the dispatch, not the route table.** `route_table_test.go` lists 18 routes
and omits `POST /api/workflows/{def}/start`, which the port suite calls in almost
every test. It is a **sample used by one test**, not the route surface; the real
surface is parsed from path segments in `server.go:297` and `api_instances.go:13`.
Concluding "no delete" from the route table would have been right by luck.

**Assessment**

Distinct from #20 and #22, and the distinction is why it is filed separately:

| | why unportable | can it be retired |
|---|---|---|
| #20 queues | cleat has no work queues | no — different architecture |
| #22 concurrency | analyzer refuses the constructs | **never** — no design could pass |
| **#23 removal** | **the machinery exists; nothing can call it** | **yes — cleat#1002** |

These eighteen are **blocked, not out of scope**. Two changes to `retentionLoop`
— one sweep at startup, and the interval as a flag — make the fifteen GC cases
portable without adding a feature, because the sweep already does what upstream
asserts. The three delete cases need a genuinely new endpoint, but one whose
implementation already exists as `DeleteCompletedWorkflows`. Written down so that
when cleat#1002 closes, the next session finds a work-list rather than
re-deriving one.

**What the port can observe today, and why it is not worth a test yet.**
`cleat_retention_last_run_timestamp` (`monitoring/prometheus/metrics.go:536`) is
exported on `/metrics` and set only at the end of a sweep, so a port could assert
it stays unset. That asserts the bug rather than the behaviour, and would have to
be deleted the day cleat#1002 lands — the opposite of the self-retiring skip this
suite prefers, where a test written to skip on a known defect starts passing when
the defect is fixed with nobody editing it.

**Method:** upstream figures are by collection, not by grep. A name grep of the
GC family gives 13: `test_garbage_collection_batched` is parametrized x3, and two
more cases join the family on reading rather than on their names. cleat#1002 was
filed with the grep estimate of ~14 and is corrected there. The cleat column is
read from `setup.go`, `config.go`, `server.go`, `api_instances.go` and
`api_admin.go` with line numbers.

**Not established:** whether the two sweeps are correct when they *do* run.
Nothing here tests the deletion logic — only that it is unreachable. The ordering
cases upstream cares most about, a row terminalizing mid-sweep and an interrupted
sweep resuming, are unexamined in cleat and may well be where the real defects
are.

## 24. A workflow result the store cannot hold is replaced with `{}` and the run reports success

**Class:** Design difference
**Upstream test:** `tests/test_failures.py::test_nonserializable_return`
**Status:** Open

**What upstream asserts**

A workflow returning a value its serializer cannot encode FAILS. The point is
not the encoder: a value that cannot be recorded must not be reported as a
recorded success.

**What cleat does**

An entry point returns a string that the engine stores in
`workflow_instances.result` -- JSONB on Postgres, JSON on MySQL, a
`CHECK (ISJSON(...))` column on SQL Server. A result no dialect can hold is
replaced with `{}` by `coerceResultJSON` (`engine/store_lifecycle.go`) and the
workflow completes.

Measured 2026-09-08 on Postgres, reading the column directly rather than the
API, with controls:

| returned by the workflow | stored | status | error_code | error_msg |
|---|---|---|---|---|
| `{"ok":true}` (control) | `{"ok": true}` | `done` | — | — |
| `{"x":123456789012345678901234567890}` (control) | unchanged | `done` | — | — |
| `not json` | **`{}`** | `done` | — | — |
| `{"x":NaN}` | **`{}`** | `done` | — | — |
| `{"x":Infinity}` | **`{}`** | `done` | — | — |

The two controls are what make the rest evidence. `big-int` is past 2**53, so it
also shows the value is not passed through a float on the way to the column.

**What is and is not silent**

The engine logs an ERROR naming the workflow and the discarded value:

    workflow result is not valid JSON and was replaced with {} -- whatever it
    carried, including any error the workflow returned, is not stored anywhere

So this is not silent to an operator reading worker logs. It is invisible to a
CALLER: `done`, no `error_code`, no `error_msg`, `result` of `{}`. A caller who
asked for a value receives an empty object and a success.

Stated because the obvious write-up -- "cleat silently discards the result" --
is wrong, and I had written it before tracing the function.

**Assessment**

A deliberate difference in part. `coerceResultJSON`'s own comments show the
trade-off was considered for the valid-but-wrong-shaped case: replacing a
storable result would destroy data, so that case is reported and stored as-is.
The invalid case has no such option -- the column would reject it -- so the
choice is between substituting and failing the workflow, and cleat substitutes.

What is not obviously deliberate is that the caller learns nothing. Upstream's
property is about the CALLER's view, and by that measure the behaviours differ:
upstream fails, cleat returns success with a substituted value. Whether to
surface it (an `error_code`, or failing the run) is a product decision, which is
why this is recorded here rather than filed as a defect.

**A second finding, from the control rather than the subject**

The large-integer case was included as a CONTROL -- to show the engine does not
mangle values merely for being awkward. It found a different defect, filed as
cleat#1022: the same result is stored exactly on PostgreSQL and narrowed to a
double on MySQL.

| dialect | `{"x":123456789012345678901234567890}` stored as |
|---|---|
| PostgreSQL | `{"x": 123456789012345678901234567890}` |
| MySQL | **`{"x": 1.2345678901234566e29}`** |

Read from the column on both, same WASM binary. The conversion is inherent to
MySQL's `JSON` type -- exact only to `BIGINT` -- so the defect is the silence
and the divergence, not the narrowing. Nothing logs it, and the degraded value
is valid JSON of the right shape.

Worth recording how it surfaced: an assertion that the result "is a number" or
"is an object" passes on both dialects. It took comparing against the exact
returned string, on more than one dialect, and it was not what the case was for.

**Tests**

`tests/test_results.py` pins the current behaviour, with the `valid` control.
The substitution test fails with instructions to invert it if cleat moves to
upstream's behaviour, and the large-integer test asserts per-dialect values --
skipping, with its reason, on any dialect nobody has measured. SQL Server is
unmeasured: `result` there is a `CHECK (ISJSON(...))` column, a third
implementation, and guessing would assert nothing.

## 25. A workflow's timeout is a worker-wide flag, not a per-run value

**Class:** Missing API
**Upstream test:** `tests/test_queue.py` — `test_unsetting_timeout`,
`test_timeout_queue_recovery`, `test_set_workflow_delay`
**Status:** Open

**What upstream asserts**

A timeout is a property of a *run*, set at the call site and inherited by
children:

```python
with SetWorkflowTimeout(2.0):
    DBOS.enqueue_workflow('test_queue', parent, child_one, child_two)
```

`parent` enqueues two children. One is wrapped in `SetWorkflowTimeout(None)`,
which **unsets** the inherited deadline; the other inherits the parent's. The
assertion is that the inheriting child is cancelled when the parent's 2s
deadline passes and the unset one survives to return its own workflow id.

So upstream is asserting three separable things: a timeout can be set per run,
it propagates to children, and propagation can be declined.

**What cleat does**

cleat has exactly one workflow timeout and it is a worker flag:

```
--max-workflow-duration  Maximum wall-clock duration per workflow execution
                         (0 = no limit). Workflows exceeding this are
                         cancelled and fail with a timeout error.
```

reaching the engine as `engine.WithDefaultWorkflowTimeout` at
`cmd/cleat-worker/setup.go:1710`. It applies to every workflow the worker runs.

The start API accepts no timeout. `handleStartWorkflow`'s request body is, in
full:

```go
Input          json.RawMessage `json:"input"`
EntryPoint     string          `json:"entry_point"`
ConcurrencyKey string          `json:"concurrency_key"`
TenantID       string          `json:"tenant_id"`
Namespace      string          `json:"namespace"` // deprecated
Priority       int             `json:"priority"`
```

There is a `timeout_ms` column, which is easy to mistake for the missing
feature and is not it: it is on `event_history`, recording the timeout of an
individual signal-await event, not a deadline for the run.

So none of upstream's three properties has a counterpart. There is no per-run
value to set, nothing to inherit, and nothing to decline — and because the
worker-wide flag applies uniformly, a parent and child always share a deadline
whether or not that is wanted.

**Why this is recorded as one gap rather than three**

`SetWorkflowTimeout(None)` is only meaningful once timeouts propagate, and
propagation is only meaningful once they can be set per run. A port of the
unsetting case cannot be written to fail for its own reason until the first
capability exists, so splitting it would create two entries that can only ever
be closed together.

**Tests**

`tests/test_timeouts.py` holds the assertion, skipped, rather than omitting it:
an absent test is indistinguishable from an untried one, and this is the first
thing a reader comparing the two systems will look for. The suite has no way to
drive `--max-workflow-duration` per test either — `CLEAT_PORTS_WORKER_EXTRA_FLAGS`
(ports#70) could start a worker with one, but a worker-wide deadline would then
apply to every other case sharing that worker.

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

**One thing deliberately not claimed**

There is a second column, `sticky_worker_id`, and it is blank on all 185 rows
too. That is **not** evidence it is cleared: sticky routing is opt-in and this
suite never exercises it, so the sample cannot distinguish "cleared at
finalize" from "never set". `assigned_to` is different — it was observed
holding a real worker id on a running row in the same database and blank once
terminal, which is direct evidence of clearing. If sticky routing does write a
durable worker id, this gap is narrower than stated and the entry should be
amended rather than closed.

**Why it matters beyond conformance**

"Which worker ran this?" is a routine operational question for a failed or slow
run, and cleat cannot answer it after the fact for any run that reached a
terminal state. Every run that is interesting to ask about is one that has
finished.

**Tests**

`tests/test_executor_identity.py`, skipped: the assertion needs a durable
executor field to read, and there is none to read.
