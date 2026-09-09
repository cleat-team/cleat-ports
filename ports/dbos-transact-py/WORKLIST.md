# Porting work-lists

One section per upstream file that has been read case by case. Each says, for
every upstream case, what cleat surface it would need and whether that surface
is present, absent, or differently shaped — so the next porting effort can start
from the answer rather than redo the reading.

**A section that is mostly "already covered" is a result, not a null result.** It
says the next effort should go elsewhere, which is otherwise unknown either way.

Upstream: `dbos-inc/dbos-transact-py`, MIT. Not vendored — this port re-expresses
assertions rather than copying source.

---

## `tests/test_failures.py` — 37 cases, read at `833794f7`

**5 portable · 9 already covered · 23 need something cleat does not have.**

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

### Already covered — 9

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

`test_dead_letter_queue` and `test_recovery_attempts` — cleat dead-letters on the
**call-retry** axis, not the workflow-recovery axis, and deliberately does not
bound reclaim. Settled in cleat#1008 and recorded as ISSUES 27; `test_dead_letters.py`
covers cleat's version.

`test_nonserializable_return` — `test_results.py::test_a_result_the_store_cannot_hold_is_replaced_and_the_run_reports_success`,
and cleat's difference (substitute rather than fail) is already written down.

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
