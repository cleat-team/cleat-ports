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
a migration guide**, which is not where anyone reading a work-list looks. Filed
as its own ISSUES entry.

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
