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
**Upstream test:** `tests/test_queue.py` — 45 of 77 cases, headed by
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
**Status:** Open — recorded as a divergence cleat is right about, not a defect

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

Either answer is defensible — from-scratch is safer if a step's side effect
might be half-applied, from-checkpoint is cheaper and uses a guarantee cleat
already makes. It should be a decision on the record rather than a consequence
of which endpoint happened to be written first.

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
