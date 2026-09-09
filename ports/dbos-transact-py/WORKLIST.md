# Porting work-lists

One section per upstream file that has been read case by case. Each says, for
every upstream case, what cleat surface it would need and whether that surface
is present, absent, or differently shaped — so the next porting effort can start
from the answer rather than redo the reading.

**A section that is mostly "already covered" is a result, not a null result.** It
says the next effort should go elsewhere, which is otherwise unknown either way.

**Four verdicts, not three.** *Portable*, *already covered*, and *needs something
cleat lacks* are the three a work-list obviously needs. The fourth is
**answered differently on purpose** — cleat does not do this, deliberately, and
the decision is recorded. It is separated out because it is the one most likely
to be misread as an absence by someone skimming for gaps, and *"we decided
against this, here is why"* is a stronger statement than *"lacks it"*.
Suggested by the rcownie-ef session while reading `test_dbos.py`.

**Blockers concentrate; they do not spread.** Three files have now been read by
three sessions independently, and each bottoms out on two or three specific
missing verbs rather than on a thin scatter across the surface:

| file | cases | the blockers, and how much they account for |
|---|---:|---|
| `test_failures.py` | 37 | per-call timeout, transactions, SQLite backend |
| `test_scheduler.py` | 35 | `apply_schedules` 8 · `trigger_schedule` 6 · `backfill_schedule` 2 — 24 of 35 |
| `test_dbos.py` | 61 | `@DBOS.transaction` 16 · step listing 7 · bulk send 5 · fork 3 — 42 of 61 |
| `test_client.py` | 57 | transactional enqueue 16 · client-library internals 14 · otel/identity/send-key 5 — 35 of 57 |

That is more actionable than a per-file portable count: **adding one verb unblocks
a double-digit number of cases in a single file.** A reader deciding what to build
should start here rather than with the totals.

Two of those blockers are recorded nowhere but a migration guide — see the
`test_dbos.py` section on `@DBOS.transaction`.

Upstream: `dbos-inc/dbos-transact-py`, MIT. Not vendored — this port re-expresses
assertions rather than copying source.

---

## `tests/test_failures.py` — 37 cases, read at `833794f7`

**5 portable · 7 already covered · 2 answered differently on purpose · 23 need something cleat does not have.**

Read case by case rather than classified by pattern. A regex over each body for
the API it drives is the obvious method and it fails in the direction that
flatters: on the sibling file it marked `test_bulk_cancel` as needing no cancel
API, because the API is `cancel_workflows` and `cancel_workflow\b` does not match
before an `s`. The cases whose names state what they need were exactly the ones
marked as needing nothing.

Validation used here, and it is the cheap version of the same idea: **cases whose
names announce their own answer are a free control.** All five agree —

| case | the name announces | classified |
|---|---|---|
| `test_step_timeout_bounds_step_duration` | a per-call timeout | lacks it |
| `test_nondeterministic_workflow_txn` | transactions | lacks them |
| `test_retriable_sqlite_exception` | a SQLite backend | lacks it |
| `test_recovery_attempts` | a workflow-level recovery bound | covered as a design difference |
| `test_nonserializable_return` | result serialization | covered |

### Portable — 5

| upstream case | property | why it is not already covered |
|---|---|---|
| `test_step_retries_no_final_sleep` | the retry loop must not sleep after the **final** failed attempt | `test_retries.py` asserts the budget is finite and what the last attempt returns; nothing asserts elapsed time **excludes** a wasted final backoff. `RetryPolicy` carries `InitialInterval`/`BackoffCoefficient`/`MaxInterval`, so the same defect is available. Upstream shipped it (their #667) |
| `test_step_retries_no_final_sleep_async` | same property | merge into the case above — the async/sync split is an SDK concern, not an engine one |
| `test_step_should_retry_on_last_attempt` | a call classified non-retryable **on its final attempt** surfaces its own error, not a wrapped retries-exhausted one | `engine.ErrorCode` has both `Permanent` and `RetriesExhausted`, so which one a client sees is a real distinction, and no case pins it |
| `test_notification_errors` | send/recv still delivers after the **notification connection is dropped** | cleat wakes on `pgNotify` with polling behind it; nothing drops the LISTEN connection and asserts a signal still arrives within a bound |
| `test_recovery_during_retries` | a worker lost **mid-retry-backoff** recovers and completes | `test_recovery.py` kills a worker during a call, not during a retry wait — a different moment in the same path |

### Already covered — 7

`test_step_retries`, `test_step_should_retry`, `test_run_step_should_retry`,
`test_run_step_async_should_retry`, `test_step_should_retry_async_validator`,
`test_step_should_retry_sync_step_async_validator_rejected` — all reduce to
*budget exhausts* and *a non-retryable failure bails on the first attempt*, which
`test_retries.py` pins as `test_the_retry_budget_is_finite`,
`test_a_failure_that_never_stops_is_retried_to_the_budget`,
`test_a_permanently_failing_call_is_not_retried` and
`test_a_permanent_status_is_attempted_once`. The upstream variants differ by call
form and by sync/async, which are Python-SDK shapes; cleat has one call form.
cleat's analogue of `should_retry` is `RetryPolicy.NonRetryableErrors`, a
substring list rather than a callback — differently shaped, same property.

`test_nonserializable_return` — `test_results.py::test_a_result_the_store_cannot_hold_is_replaced_and_the_run_reports_success`,
and cleat's difference (substitute rather than fail) is already written down.

### Answered differently on purpose — 2

`test_dead_letter_queue` and `test_recovery_attempts`. cleat dead-letters on the
**call-retry** axis — a durable call ran out of its budget — not on the
workflow-recovery axis, and it deliberately does not bound reclaim at all. That
was the open question in cleat#1008; it was decided (record the count, decline
the bound), shipped as cleat#1055, and written up as ISSUES 27.
`test_dead_letters.py` covers cleat's version of the behaviour.

These are not gaps and should not be counted as ones. Anybody reading this file
for work to do should skip them; anybody reading it to understand why cleat
differs should start here.

### Needs something cleat does not have — 23

**A per-call timeout — 9 cases.** `test_step_timeout_bounds_step_duration`,
`_is_checkpointed_and_replayed`, `_preserves_step_outcomes`, `_with_retries`,
`_via_run_step`, `_inert_outside_workflow`, `_rejects_invalid_config`,
`_with_workflow_cancellation`, `_does_not_claim_a_cancelled_step`.

`cleat.RetryPolicy` is `MaxAttempts`, `InitialInterval`, `BackoffCoefficient`,
`MaxInterval`, `NonRetryableErrors` — **no timeout field**. `CallErrorTimeout`
exists as a *result* code, meaning something timed out, not as a bound a guest
can set. Note this is a different axis from ISSUES 25, which is the per-*run*
timeout; both are absent and they are not the same feature. This is the largest
single block in the file and one feature unlocks all nine.

**Transactions — 3.** `test_transaction_errors`, `test_invalid_transaction_error`,
`test_nondeterministic_workflow_txn`. `@DBOS.transaction()` gives guest code a SQL
session against the system database; cleat's guest reaches the outside only
through host calls and plugins, so there is nothing to map.

**Fork — 1.** `test_nondeterministic_workflow` needs `fork_workflow(id, step)` to
resume from a chosen step with changed code, plus unexpected-step detection.
ISSUES records detached runs as the nearest thing cleat has, and it is not this.

**DBOS-internal surfaces — 6.** `test_recv_consume_idempotent_on_db_retry`,
`test_recv_consume_idempotent_on_timeout`, `test_record_child_workflow_idempotent_on_db_retry`,
`test_record_get_result_increments_function_id_once_on_db_retry` drive the sys-db
layer directly rather than any user-visible API; `test_get_result_no_hang_on_connection_invalidated_error`
is about their SQLAlchemy engine; `test_retriable_sqlite_exception` needs a SQLite
backend cleat does not have.

**Host-process and SDK semantics — 4.** `test_keyboardinterrupt_during_retries`
(a guest cannot receive a host signal), `test_error_serialization` (round-tripping
Python exception classes), `test_workflow_error_serialization` (needs per-step
error records on a list-steps API), `test_step_status` (needs the current attempt
number readable from inside a call).

### What this says about where to go next

The retry surface is thoroughly covered and the four remaining portable cases are
narrow. **The largest concentration of unportable value is one feature — a
per-call timeout — and it accounts for nine of the thirty-seven.** If anything in
this file is worth building toward, it is that.

---

## `tests/test_scheduler.py` — 35 cases, read at `833794f7`

**5 portable · 6 already covered · 24 need something cleat does not have.**

Count reconciled against the inventory before classifying: 35 by `grep -cE "^(async )?def test_"`, 35 unique names, and 35 by the collection method `scripts/count-queue-cases.py` uses. No parametrize expansion in this file. (I first reported 34 — from counting a printed listing by eye rather than running `-c`. The grep never disagreed with the table; I did.)

### cleat's actual schedule surface

Established from the **store methods**, not the HTTP routes — routes are what happens to be exposed, store methods are what exists:

    ClaimDueSchedule  CreateSchedule  DeleteSchedule
    GetDueSchedules   GetDueSchedulesAcrossTenants
    ListSchedules     SetScheduleEnabled

`Schedule` carries `Name`, `DefName`, `EntryPoint`, `CronExpression`, `Input`, `Enabled`, `NextRunAt`, `LastRunAt`, `Timezone`, `MisfirePolicy`, `CatchUpLimit`, `OverlapPolicy`, `LastRunID`, `TenantID`.

**There is no get-by-name, no update, no trigger and no backfill.** Those four absences account for sixteen of the twenty-four blocked cases.

### Portable — 5

| upstream case | property |
|---|---|
| `test_dynamic_scheduler_replace_schedule` | replacing a schedule's definition takes effect and the old one stops firing — cleat has no update, but delete+create is the same property |
| `test_long_schedule_shutdown` | a long-running scheduled workflow does not block worker shutdown |
| `test_backfill_with_timezone` | a cron in a named zone fires at the right wall-clock instant — cleat models `Timezone`, so this is portable without the backfill *call* |
| `test_backfill_naive_datetime` | the naive/aware distinction, against cleat's `DefaultScheduleTimezone` |
| `test_scheduled_workflow_datetime_with_portable_serializer` | a scheduled run's input survives the store unchanged |

### Already covered — 6

`test_dynamic_scheduler_fires` → `test_a_cron_schedule_actually_starts_its_workflow`.
`test_dynamic_scheduler_delete_stops_firing` → `test_deleting_a_schedule_removes_it`.
`test_dynamic_scheduler_add_after_launch` → `test_a_workflow_can_register_a_cron_schedule`.
`test_pause_resume_schedule` → `test_disabling_a_schedule_stops_it_firing` + `test_re_enabling_a_schedule_resumes_it` — cleat spells pause/resume as `enable`/`disable`.
`test_automatic_backfill_on_restart` → `test_misfire.py::test_a_schedule_set_to_catch_up_delivers_what_it_missed`; upstream calls it backfill, cleat calls it `misfire_policy: catch_up`.
`test_schedule_crud` → `test_the_schedule_policies_round_trip_through_the_api` plus the create/delete cases.

### Needs something cleat does not have — 24

**`apply_schedules` — 8.** Declarative reconciliation of a schedule *set*: `test_apply_schedules`, `_optional_context`, `_concurrent`, `_live_update`, `_preserves_runtime_state`, `test_list_schedules_undeserializable_context`, `test_client_apply_schedules`, `test_client_apply_schedules_optional_context`. cleat creates and deletes schedules one at a time and has no notion of converging a declared set.

**`trigger_schedule` — 6.** Firing a schedule on demand: `test_trigger_schedule`, `test_client_trigger_schedule`, `test_list_workflows_by_schedule_name`, `test_schedule_name_survives_export_import`, `test_static_class_method_schedule`, `test_classmethod_schedule`. The last two also need Python class-method decorator ergonomics. `test_list_workflows_by_schedule_name` additionally needs runs to be queryable by the schedule that started them — cleat records only `LastRunID`.

**Explicit `backfill_schedule` — 2.** `test_backfill_schedule`, `test_client_backfill_schedule`. Distinct from `misfire_policy: catch_up`, which is automatic and already covered: these ask for a *range* to be replayed on demand.

**A separate client API surface — 3.** `test_client_schedule_crud`, `test_client_pause_resume_schedule`, `test_client_schedule_crud_async`. `DBOSClient` is a second entry point; cleat has one HTTP API.

**Python SDK shapes — 5.** `test_schedule_crud_async` (async mirror), `test_instance_method_schedule_rejected`, `test_schedule_thread_signature` (scheduler-thread introspection), `test_schedule_crud_from_workflow` (schedule CRUD as host calls from *inside* a guest — not among cleat's exports), `test_scheduled_workflow_datetime_with_portable_serializer`'s class-registration half.

**Queues — 1.** `test_schedule_with_queue_name`, which cleat has no analogue for.

### Validation

Cases whose names announce their own answer, as a free control — all agree:

| case | the name announces | classified |
|---|---|---|
| `test_schedule_with_queue_name` | a queue | lacks it |
| `test_client_trigger_schedule` | a trigger verb, via the client | lacks both |
| `test_instance_method_schedule_rejected` | Python instance-method binding | SDK shape |
| `test_automatic_backfill_on_restart` | backfill after an outage | covered by `misfire_policy: catch_up` |
| `test_pause_resume_schedule` | pause/resume | covered by enable/disable |

Checked as a **partition**: every one of the 35 appears in exactly one bucket, none twice, none missing. `5 + 6 + 24 = 35` holds just as well with one case dropped and another double-counted.

---

## `tests/test_dbos.py` — 61 cases, read at `833794f7`

**17 portable · 0 already covered · 2 answered differently on purpose · 42 need something cleat does not have.**

Count reconciled before classifying: 61 by `def`, and **zero** parametrize
expansion, so def-count equals collection count here and matches the inventory
table's 61. Checked because the 44-vs-46 discrepancy on
`test_workflow_management.py` was entirely one `@parametrize`d case.

### What blocks the 42

| blocker | n | evidence |
|---|---:|---|
| no `@DBOS.transaction` equivalent | 16 | `docs/migration/from-dbos.md:23` and `:386` |
| internal API as setup — see below | 13 | `_sys_db` / `sql_session` |
| no step listing | 7 | `list_workflow_steps`, `step_status` |
| no bulk send | 5 | `send_bulk` |
| no fork | 3 | `fork_workflow` |

### The transaction gap is documented outside the ledger

`docs/migration/from-dbos.md` states it twice — a mapping row at `:23`
(`@DBOS.transaction` → `call("database", "query", ...)`) and a section at `:386`,
*"No `@DBOS.transaction` Equivalent"*: workflows run in WASM and cannot reach a
database directly. `grep -inE "transaction|sql_session"` over ISSUES.md returns
nothing.

**16 of 61 cases in a priority-2 file bottom out on a limitation recorded only in
a migration guide**, which is not where anyone reading a work-list looks.

**Correction, 2026-09-09.** This paragraph originally ended "Filed as its own
ISSUES entry." It was not. The same `grep -inE "transaction|sql_session"` that
this section quotes as its REASON for filing still returns nothing, which is
how cleat-ws3 found it while surveying `test_client.py` — the sentence asserted
the outcome of a command it had just reported failing, one paragraph earlier.
The entry is still owed and is deliberately not being squeezed into this
change: ports#111 files the CALLER-side transactional gap, this is the
WORKFLOW-side one, and both are 16 cases, which is exactly the coincidence that
would get them merged into one entry by whoever wrote them in a hurry.

### The 13 "internal API" cases are setup, not subject

A first pass classified everything touching `_sys_db`/`sql_session` as
declined-on-contract, following the reasoning used for
`test_workflow_management.py`, and produced 23. But the assertion is never on the
internal API — those cases *force a state* and then assert on behaviour:

    test_recovery_thread            set_workflow_status(dbos._sys_db, wfuuid, "PENDING")
    test_recovery_reenqueue_...     with dbos._sys_db.engine.begin() as c:

Splitting subject from setup gives **zero** cases asserting on internals. So the
decline-on-contract reasoning, correct for that other file, does not transfer
here — and cleat can reach those states another way: kill the worker and let the
reaper reclaim, which `test_recovery.py` already does.

**Portable via that route — 6:** `test_recovery_thread`,
`test_recovery_workflow_step`, `test_recovery_empty_id_dead_letters`,
`test_recovery_reenqueue_is_ownership_conditional` (the property is the ownership
fence, cleat's `WHERE assigned_to = ? AND generation = ?`),
`test_simple_workflow_attempts_counter` (cleat gained `reclaim_count` in
cleat#1055), `test_workflow_returns_none`.

**The subject really is a DBOS implementation detail — 3:** these assert on
PostgreSQL triggers *by name* and on `sys_db.notifications_map` —
`test_recv_wakeup_trigger_is_kept` (*"dbos_notifications_trigger must be kept"*),
`test_get_event_delivered_by_notifier_without_trigger` (*"should have been
dropped"*), `test_notification_fallback_polling`. Read in full; these three are
why the split had to be done case by case rather than by rule.

**Already a recorded gap — 2:** `test_workflow_timeout` (ISSUES 25),
`test_eid_reset` (no durable record of which worker ran a workflow).

### Answered differently on purpose — 2

`test_recovery_appversion` — DBOS pins a run to an application version because
code ships with the process. cleat pins code in the database
(`workflow_defs.wasm_bytes`), so there is no worker lacking the code and nothing
to hold a run for. Investigated and closed as not-a-gap; `test_versions.py`
covers cleat's version of the property, and ports#91 covers the guarantee
underneath it.

`test_workflow_wrapped_by_custom_decorator` — Python decorator composition. SDK
ergonomics, not engine behaviour.

### Validation, including where the check was wrong

| case | the name announces | classified | |
|---|---|---|---|
| `test_send_bulk_send_to_forks` | fork | needs fork | ok |
| `test_nested_steps` | step listing | needs step listing | ok |
| `test_duplicate_recovery_does_not_rerun_running_workflow` | recovery | no explicit recovery API | ok |
| `test_recovery_workflow` | recovery | internal API | **check wrong** |
| `test_recovery_thread` | recovery | internal API | **check wrong** |

**The last two are the useful rows.** The validator expected a recovery case to
classify as needing a recovery API; first-match ordering put `_sys_db` ahead of
it, so the check reported MISS while the classifier was right. Reordering the
blockers would have produced a clean, plausible, still-wrong table.

What stopped that was that **four** recovery cases missed together: one looks
like a bad rule, four look like a bad question. Chasing it is what exposed the
setup/subject conflation above, which moved 10 cases out of "declined".

A validation table that only ever confirms is the same trap one level up.
Recorded here rather than silently corrected.

### Confidence

The four ambiguous cases were classified by reading their assertions. The other
nine internal-API cases were classified from setup lines and names, which is
weaker — open the case before trusting its bucket.

## `tests/test_client.py` — 57 cases, read at `833794f7`

**3 portable · 13 already covered · 6 already a recorded gap · 35 need something
cleat does not have.**

Count reconciled before classifying, by a route independent of the README: 54
`def`s expand to 57 collected cases, because `test_client_enqueue_rejects_empty_workflow_id`
is `@parametrize`d ×3 and `test_set_workflow_id_rejects_empty` ×2. That matches
the inventory table's 57. Checked first because the same discrepancy on
`test_workflow_management.py` was entirely one parametrized case.

### The name census is worthless here, and that is the finding about method

    for nm in <54 upstream names>: grep -rl "$nm" tests/ ISSUES.md README.md

**0 of 54.** Not one upstream name appears anywhere in this port, while the
inventory credits the file with 8 cases. `grep -n "test_client.py" ISSUES.md`
also returns nothing, so the one command that removed two thirds of the
`test_workflow_management.py` job removes none of this one.

That is the inverse of agent1's result (1 name found, 12 actually covered) in a
sharper form, and it settles the rule rather than illustrating it: **a name
census is a lower bound on coverage and never an upper one.** Here the lower
bound is zero and the true figure is 13. Every case below was read.

### Where the 57 go

| bucket | cases | recorded as |
|---|---:|---|
| transactional enqueue / send | 16 | **not previously recorded** — ISSUES 31 |
| DBOS client-library internals | 14 | not an engine assertion; see below |
| already covered here | 13 | table below |
| already a recorded gap | 6 | ISSUES 20, 25; `test_dbos.py` §; #107 |
| mechanism gap, not previously recorded | 5 | otel attributes 3 · send idempotency 1 · caller identity 1 |
| **portable** | **3** | one case, parametrized ×3 |

### The largest bucket is a second transaction gap, and it is not the recorded one

Sixteen cases — `test_{enqueue,send}_in_transaction_*`, `test_send_bulk_in_transaction`,
`test_enqueue_and_send_in_transaction` — enqueue a workflow or post a message
**inside the caller's own SQLAlchemy transaction on the system database**, so the
enqueue commits or rolls back atomically with the caller's business writes.
`test_enqueue_in_transaction_pre_commit_invisible` is the property in one line: a
concurrent reader must not see the workflow before the caller's transaction
commits.

**This is not the `@DBOS.transaction` gap the `test_dbos.py` section records**, and
the two must not be merged — they happen to be 16 cases each, which is exactly the
kind of coincidence that invites it.

| | `@DBOS.transaction` (recorded) | `enqueue_in_transaction` (this) |
|---|---|---|
| who runs SQL | **workflow** code, inside a step | the **caller**, outside cleat |
| what cleat lacks | guest code cannot reach a database from WASM | the client cannot join a caller's transaction |
| recorded at | `docs/migration/from-dbos.md:386` | nowhere — filed as ISSUES 31 |

`grep -inE "enqueue_in_transaction|send_in_transaction" ` over
`docs/migration/from-dbos.md` returns nothing; §2 there is about workflow code
only. cleat's client is HTTP, so there is no connection to enlist and no shape
this could take without a different client.

**Separately, and worth someone checking:** the `test_dbos.py` section says the
`@DBOS.transaction` gap was *"Filed as its own ISSUES entry"*, and
`grep -inE "transaction|sql_session" ISSUES.md` still returns nothing — the same
command that section quotes as its reason for filing. Not acted on here because
it is another section's claim, but the ledger and the work-list disagree.

### DBOS client-library internals — 14

These assert on the Python client object, not on durable execution. cleat's
client is HTTP and has none of these properties, so there is nothing to answer
differently *or* to lack.

**Construction and connection — 6.** `test_client_no_migrate` (the client
migrates the system database), `test_client_bad_url`, `test_client_lazy_defers_connecting`,
`test_client_lazy_connects_on_first_use`, `test_client_lazy_rejects_listen_notify`,
`test_client_no_retry_raises_on_unreachable_database`.

**Delivery mechanism and its performance — 5.** `test_client_no_listener_by_default`
asserts a private attribute is `None`; `test_client_listen_notify_get_event` needs
PostgreSQL `LISTEN`/`NOTIFY`; `test_client_get_event_prompt_delivery` and its async
twin assert `elapsed < 30` to prove the client re-polls;
`test_client_get_event_async_does_not_pin_a_thread_per_wait` asserts 64 concurrent
waits are not capped by `min(32, cpu + 4)` executor threads.

**Neither of the above — 3.** `test_db_retry_connection_error_opt_out` drives a
decorator against a *fake* database class and never touches DBOS at all;
`test_set_workflow_id_rejects_empty` (2 cases) tests a Python context manager's
constructor.

The distinction that matters for the ledger: **none of these is "cleat lacks the
mechanism"**, so none belongs in ISSUES. Filing them there would inflate the gap
with assertions no engine could make.

### Already covered here — 13

Coverage is by assertion, not by name; none of these names appears in the tree.

| upstream | covered by |
|---|---|
| `test_client_enqueue_and_get_result` | `test_api_surface.py` (the run appears in `/api/workflows`) |
| `test_client_enqueue_idempotent` | `test_queues.py::test_the_same_idempotency_key_starts_one_run` |
| `test_client_enqueue_appver_not_set` · `_appver_set` | `test_versions.py::test_the_version_reported_is_the_deployed_one` |
| `test_client_send_with_topic` | `test_api_surface.py::test_a_signal_delivered_over_http_reaches_the_workflow` |
| `test_client_send_no_topic` | `test_send.py::test_a_fire_and_forget_send_reaches_the_service` |
| `test_client_get_event` · `_finished` | `test_query_state.py::test_query_state_is_readable_while_the_workflow_is_suspended` |
| `test_client_get_event_update` · `_update_finished` | `test_query_state.py::test_a_reader_sees_the_current_value_not_the_final_one` |
| `test_client_retrieve_wf` · `_done` | `test_api_surface.py` + `cleat.get` / `await_terminal` |
| `test_enqueue_with_priority` | `test_queues.py::test_priority_is_accepted_and_recorded`, `test_priority_order.py` |

**13 here against the inventory's 8 is not a discrepancy.** The `Cases here`
column counts *our* cases attributed to the file (ports#92); this counts
*upstream* cases with a local equivalent. `test_api_surface.py` has exactly 8
cases and the coverage above is spread over six files.

### Already a recorded gap — 6

`test_enqueue_with_timeout` — ISSUES 25, the timeout is a worker-wide flag.
`test_enqueue_with_deduplication` and `test_client_enqueue_wrong_appver` — ISSUES 20,
both need a queue to sit in (`list_queued_workflows`, status `ENQUEUED`).
`test_client_fork` and `test_client_fork_async` — the fork bucket agent1 opened
in ports#107. `test_client_send_bulk` — the `test_dbos.py` section already
records *no bulk send*, at 5 cases; this is its sixth.

### Mechanism gap, not previously recorded — 5

**otel carrier and caller attributes — 3.** `test_client_enqueue_with_otel_context`,
`_without_otel_context`, `_otel_context_without_active_span`. DBOS stores the
caller's `attributes` dict on the run and, if an otel context is supplied,
injects a `traceparent` carrier beside it. cleat extracts a **trace id only** —
`extractTraceIDFromTraceParent(r.Header.Get("traceparent"))` at
`cmd/cleat-worker/server.go:611` — and there is no per-run attributes bag to put
a caller's own keys in. The middle case is the one worth keeping: absent an otel
context, attributes must survive *unchanged*, which is an assertion about not
corrupting caller data.

**Idempotent send — 1.** `test_client_send_idempotent` posts the same message
twice under one key and asserts one notification row. cleat's `Idempotency-Key`
header is read only by the **start** handler; the signal endpoint takes no key.

**Caller identity on a run — 1.** `test_client_auth` records `authenticated_user`
and `authenticated_roles` on the run and reads them back from the listing. cleat
authenticates a **tenant**, not a user: `auth.TenantIDFromContext` is what the
start handler consults, and nothing records who started a run. `from-dbos.md:378`
states the position — *"Authentication is handled at the host level (API keys,
middleware), not in workflow code"* — so this is a deliberate difference, but the
*record* of it, which is what the test asserts, does not exist either. Related to
ISSUES 26 (nothing records which worker ran a workflow) without being the same
question.

### Portable — 3

One case, parametrized ×3: **`test_client_enqueue_rejects_empty_workflow_id`**,
upstream's #759 — an empty or whitespace id must be *rejected*, not inserted
verbatim, and `_workflow_exists` then confirms nothing was written.

cleat generates the run id server-side, so the direct analogue does not exist.
The nearest caller-supplied identifier is the `Idempotency-Key` header, and the
guard on it is a bare emptiness test with no trim, on every dialect:

    cmd/cleat-worker/server.go:599   idempotencyKey := r.Header.Get("Idempotency-Key")
    engine/store_lifecycle.go:753    if idempotencyKey != "" {      // postgres
    engine/mysql_lifecycle.go:571    if idempotencyKey != "" {      // mysql
    engine/mssql_lifecycle.go:1074   if idempotencyKey != "" {      // sqlserver

`""` means "no key" and skips the block. `"   "` is not `""`, so it is hashed and
stored as a real key. Within one tenant, any two unrelated requests that both
send a blank-but-present key are then deduplicated onto the same run: the second
gets the first's workflow id with `already_started: true`, and its own workflow
never starts. `grep -rn "Idempotency-Key" --include='*.go' cmd/ engine/` shows no
validation anywhere between the header and the hash, and no test covers it.

**Stated as read, not run.** The chain above is three hops with no branch between
them, but nothing here has executed it, and this port's own history is a series
of cases where the live path differed from the readable one. **That is the
portable case**: one test that sends `Idempotency-Key: "   "` twice with different
payloads and asserts two runs — which either confirms the reading or refutes it,
and is worth having either way. Deliberately *not* filed as a cleat defect until
someone runs it.

### Validation

- Partition is total and disjoint over the 54 defs, checked in code:
  no duplicates, none unassigned, no phantom names. Sums to **54 defs / 57
  cases** by both routes.
- The 16-case transactional bucket was selected by name (`"_in_transaction" in n`)
  and then re-derived by **call graph** — every test that calls
  `enqueue_in_transaction` / `send_in_transaction` / `send_bulk_in_transaction`.
  The two sets are identical, in both directions. A name filter over Python
  source is the weakest tool in this repo's collection, so it does not get to
  stand alone.
- `python3 ports/dbos-transact-py/scripts/count-queue-cases.py --check` →
  `README.md inventory tables match the tree`, exit 0. No tests added, so the
  inventory is unchanged by construction.

**A partition that adds up is not a partition that is right** — agent1's summed
to 44/46 in both its wrong and its right version. The call-graph re-derivation is
here because of that, and it is the only independent check this classification
has: unlike `test_workflow_management.py`, there was no prior ISSUES claim to
reconcile against, because ISSUES.md does not mention this file at all.

### What this says about where to go next

Six of the eight upstream files are now surveyed and the shape has not varied:
the per-file numbers are **ceilings**. This one is the most extreme yet — **3
portable of 57**, and the 3 are one parametrized case about input validation.

35 of 57 need something cleat does not have, and 30 of those 35 are one
architectural fact: **DBOS's client is a library holding a database connection,
and cleat's is HTTP.** Transactional enqueue (16), client construction and
connection (6), delivery mechanism (5), and the caller-identity and otel records
(4) are all downstream of it. That is not a backlog; it is a boundary, and no
amount of porting moves it.

---

## `tests/test_async.py` — 33 cases, read at `833794f7`

**1 portable · 11 already covered · 1 answered differently on purpose · 9 need
something cleat does not have · 11 are not engine assertions at all.**

**Five verdicts here, not four.** The fifth was predicted by the rcownie-ef
session before the reading started, and it turns out to be the largest bucket in
the file: a third of these cases assert something about the **Python SDK's own
async machinery** — its notification maps, its poll loop, which event loop a
coroutine runs on, whether `destroy()` deadlocks. There is no engine claim in
them to port. That is a different statement from "cleat lacks this", and
collapsing the two would read as nine more gaps than exist.

### Why this file needed reading rather than a shrug

README called it priority 3 and *"mostly the async mirror of assertions this port
already makes in sync form"*. **The conclusion survives; the reason given for it
does not.** The mirror bucket is 11 of 33, not the ~23 the README claimed — so
"mostly" was wrong, and it was wrong in the direction that invites someone to
port them for completeness. The accurate reason to skip this file is stronger:
**a third of it is not about a durable-execution engine at all.**

The README also said "of its 32 cases" while its own generated table said 33.
`test_async_wait_does_not_recheck_past_its_deadline` is parametrized over
`["get_event", "recv"]`, so 32 functions collect as 33 cases — the definitions-
versus-cases distinction the README documents two sections above the place it
then got wrong.

### Portable — 1

`test_max_parallel_workflows` — 50 workflows that each sleep 5s complete in under
30s, both started directly and enqueued. Serial execution would take 250s, so the
wall clock is the assertion.

**Nothing in this port asserts that workflows run in parallel.** The closest is
`test_concurrency.py::test_distinct_keys_do_not_block_each_other`, and it does
not: it asserts both starts are *admitted* (201) and both *complete*, which a
worker executing them one after another satisfies. It was written to stop the
neighbouring rejection test passing vacuously, and it does that job; it was never
about throughput.

So this is not an async mirror. It is an assertion the sync suite does not make
either, and it is the one case in this file worth porting.

### Already covered — 11

Each names the local test that makes the same assertion under a different name.
`test_async.py` shares no test name with anything in `tests/`, so a name-level
grep finds nothing and is worthless here in both directions.

| upstream | asserted here by |
|---|---|
| `test_async_workflow` | `test_queues.py::test_the_same_idempotency_key_starts_one_run` |
| `test_async_step` | same |
| `test_async_completed_replay_no_hook_rerun` | `test_queues.py::test_a_completed_run_still_answers_for_its_idempotency_key` (#108) |
| `test_send_recv_async` | `test_signals.py`, all three |
| `test_set_get_events` | `test_query_state.py` ×2, `test_api_surface.py::test_recorded_events_are_readable_while_a_workflow_is_suspended` |
| `test_sleep` | `test_replay.py::test_the_virtual_clock_advances_across_a_sleep` |
| `test_start_workflow_async` | `test_api_surface.py::test_the_workflow_list_contains_a_run_that_was_started` |
| `test_retrieve_workflow_async` | `test_results.py::test_a_storable_result_survives_unchanged` |
| `test_unawaited_workflow` | `test_detached.py` ×2 |
| `test_child_workflow_async` | `test_children.py::test_children_actually_ran_as_separate_workflows` |
| `test_workflow_recovery_async` | `test_recovery.py::test_a_workflow_survives_the_loss_of_its_worker` |

Two of these carry an SDK assertion alongside the engine one, and only the engine
half is covered: `test_start_workflow_async` also asserts the workflow and step
ran on the caller's event loop, and `test_workflow_recovery_async` also asserts
the recovered workflow did. Neither has a counterpart in a port whose workflows
are Go compiled to WASM.

### Answered differently on purpose — 1

`test_workflow_with_task_cancellation` — cancelling the asyncio task that awaits a
handle must not cancel the workflow.

**This port cannot make the assertion false.** Upstream the awaiting task and the
running workflow share a process, so the coupling is real and worth pinning. Here
the client is an HTTP poller and cancellation is an explicit API call, so
abandoning a read has no path to the run. Porting it would produce a test that
passes by architecture rather than by behaviour — which is the shape of assertion
this suite has been burned by before.

### Needs something cleat does not have — 9

**Concurrent steps inside one workflow — 5.** `test_asyncio_wait`,
`test_asyncio_wait_all_completed`, `test_asyncio_wait_first_exception`,
`test_asyncio_wait_timeout`, `test_concurrent_patch_async`. All drive several
step coroutines of **one** workflow concurrently. ISSUES 22: cleat's determinism
analyzer refuses that family at build time (E001/E002/E012/E013), so there is no
form of these to write. The first four additionally assert on
`fork_workflow_async` and on a recorded step list, neither of which cleat has.

**Enumerate what a workflow published — 1.** `test_get_events_async` reads every
event of a workflow at once via `get_all_events_async`. ISSUES 28, which already
records this for the four sync cases in `test_workflow_management.py` and gives a
reason to decline them independently of whether cleat grows the capability.

**Workflow-level timeout with deadline propagation — 1.**
`test_workflow_timeout_async` sets a timeout on a parent and asserts the deadline
propagates to children started both ways. ISSUES 25: cleat's timeout is a
worker-wide flag, not a per-run value. `test_timeouts.py::test_a_child_can_decline_the_deadline_it_inherits`
is the nearest thing here and asserts the opposite direction — that a child may
decline what it inherits.

**Bulk send — 1.** `test_send_bulk_async` sends several messages in one call, from
inside and outside a workflow, recorded as a single step. Already counted as a
blocker in the `test_dbos.py` section above ("bulk send 5"), so this is a sixth
case behind the same missing verb.

**Address a detached run — 1.** `test_unawaited_workflow_exception` starts a child
without awaiting it and then retrieves it by ID to assert its exception surfaces.
`RunDetached` returns no handle and accepts no caller-chosen ID, so the child
cannot be addressed at all. Already recorded as the skip on
`test_detached.py::test_a_detached_run_can_be_addressed_by_its_caller`; this is
the failing-child half of the same gap.

### Not an engine assertion at all — 11

These assert properties of `dbos`'s own async implementation. Listed rather than
counted, because "11 cases we are not porting" invites the question and the names
answer it:

| case | what it asserts |
|---|---|
| `test_recv_async_cancelled_during_setup` | a cancelled `recv` leaves no entry in the SDK's `notifications_map` |
| `test_get_event_async_cancelled_during_setup` | same, for `workflow_events_map` |
| `test_async_wait_does_not_recheck_past_its_deadline` ×2 | the SDK's poll loop issues no query after its own deadline |
| `test_async_tx_raises` | `@DBOS.transaction` refuses an `async def` at registration |
| `test_main_loop` | an enqueued coroutine runs on the adopted main event loop |
| `test_destroy_from_adopted_main_loop_does_not_deadlock` | `DBOS.destroy()` does not deadlock against its own loop |
| `test_submit_coroutine_from_own_loop_raises_instead_of_hanging` | `BackgroundEventLoop.submit_coroutine` raises rather than hangs |
| `test_async_child_id_survives_concurrent_context_clear` | a monkeypatched race in `_sys_db` leaves no empty ids |
| `test_failed_dequeued_async_workflow_leaves_no_unretrieved_future` | asyncio logs no "never retrieved" error |
| `test_record_child_workflow_rejects_empty_id` | `_sys_db.record_child_workflow` rejects an empty id |

Every one of them would still be a valid test of `dbos` if its storage layer were
replaced. That is the test for this bucket, and it is why they are not gaps.

### Validation, and where the classification was wrong

Classified twice, by deliberately different routes, so the two could disagree:
by reading each case's assertions, and mechanically by whether its body touches
`_sys_db`, `dbos._`, `BackgroundEventLoop`, `get_running_loop`, `monkeypatch` or
`SystemSchema`.

**They disagreed on five of 33, which is the only reason the final answer is
trustworthy.** The totals were 12 and 13 — close enough to have been rounded away
as a judgement difference, which is exactly how the `test_workflow_management.py`
mis-bucketing survived until an independent count contradicted it.

| case | mechanical | reading | adjudicated |
|---|---|---|---|
| `test_start_workflow_async` | internal | mirror | **mirror** — one trailing loop-identity line, engine assertions throughout |
| `test_workflow_timeout_async` | internal | needs mechanism | **needs mechanism** — `_timeout_tasks` is a drain check, not the subject |
| `test_workflow_recovery_async` | internal | mirror | **mirror** — the direct `UPDATE` sets up a crash; the assertion is recovery |
| `test_async_tx_raises` | — | internal | **internal** — needs no privates to be purely about registration |
| `test_concurrent_patch_async` | — | internal | **needs mechanism** — the reading was wrong; it is `asyncio.gather` inside one workflow, ISSUES 22 |

Four of five went to the reading, which is the expected direction: touching a
private is a proxy for "about the SDK", and a proxy over-matches on setup code.
The fifth went the other way and is the one that mattered — `patch_async` is a
public API, so nothing mechanical flagged it, and calling it "SDK internals"
would have hidden a case that ISSUES 22 already accounts for.

**The partition summed to 33 in both versions.** As the `test_workflow_management.py`
section says: a partition that adds up is not a partition that is right.

### What this says about where to go next

Nowhere, and that is the result. One portable case, and it is not an async
assertion at all — it is a throughput assertion this suite has never made in
either form. Everything else is covered, structurally inapplicable, or behind a
blocker already recorded against another file.

**No new ISSUES entry.** Every gap this file reaches is 22, 25 or 28, or the
`RunDetached` handle gap already recorded as a skip. That is the fourth file in a
row to bottom out on blockers that were already known, which is the strongest
available evidence that the ledger is closed under this upstream suite.

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

## `tests/test_concurrency.py` — 11 cases, read at `833794f7`

**ISSUES.md 22 had already surveyed this file**, and the grep that found it took
one command. The entry classifies nine of the eleven as unportable in principle
— `asyncio.gather` inside a single workflow, which cleat's determinism analyzer
refuses at build time rather than at run time (E001/E002/E012/E013) — and names
the remaining two as "the work-list for this file".

So this section is not a survey. It is the two cases entry 22 left, read and
disposed of.

| upstream case | disposition |
|---|---|
| `test_concurrent_workflows` | **ported** — `test_identity_isolation.py` |
| `test_concurrent_getevent` | open, see below |

### `test_concurrent_workflows`, and why it is not the smoke test it looks like

Ten workflows started from a thread pool, each under a caller-supplied id, each
returning its own. Read quickly it asserts "ten workflows finish". The
assertion that carries it is `assert id == future.result()` — **each run
returns ITS OWN id** — and that is the only case in the file that would catch a
host handing a running workflow somebody else's identity.

cleat is where that is most expressible. One worker runs many workflows at
once, each is a WASM instance the host drives, and `RunID()` is answered out of
host state rather than out of anything the guest holds. A pooled instance, a
reused context, or an index into a slice of in-flight runs all produce the same
symptom: **ten workflows that complete perfectly and report the wrong
identity.**

Two things the port adds that upstream does not have:

- **An overlap assertion.** Ten sequential 1.5s runs satisfy every identity
  assertion while demonstrating nothing about concurrency, and nothing in the
  output would say so. The test measures wall time and requires it under half
  the serial cost.
- **Per-run pairing rather than set equality.** Asserting the ten returned ids
  equal the ten started ids is weaker and a full permutation satisfies it: a
  host that gave every run its neighbour's identity returns exactly the right
  *set*. The test compares each run against the id it was started under.

Falsified by doctoring the workflow to return a constant instead of `RunID()`:
10 of 10 mismatched, **and all ten runs still reached `done`** — which is the
test's own claim about what a completion-only check cannot see.

### `test_concurrent_getevent` — open

Two threads call `get_event` on the same run and event name while a third runs
the workflow that sets it; both readers must receive the same value. cleat's
nearest surface is signals and promises rather than a keyed event map, and
`test_promises.py` / `test_signals.py` cover single-reader delivery. **Whether
two concurrent readers of one promise both observe it is untested here**, and
it is a real question rather than a mechanical port — ISSUES.md 28 records that
a workflow's readers are all keyed, so the shape of the upstream assertion may
not have an analogue at all. Left open deliberately rather than ported badly.

Upstream's final line, `assert not dbos._sys_db.workflow_events_map._dict`,
asserts on SDK internals and has no counterpart in any engine.

### Where this leaves the file

11 upstream cases: 9 unportable in principle (ISSUES 22), 1 ported here, 1
open. **The ceiling is 2, and it is now 1 of 2.** As with `test_queue.py` and
`test_workflow_management.py`, the coverage column is a ceiling and not a
backlog.
