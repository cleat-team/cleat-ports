## `tests/test_dbos.py` — 61 cases, read at `833794f7`

**2 portable · 3 already covered · 0 answered differently on purpose · 46 need
something cleat does not have · 10 are not engine assertions at all.**
(2 + 3 + 46 + 10 = 61.)

> **This line has been rewritten twice.** It read *"17 portable · 0 already
> covered · 2 answered differently on purpose · 42 need something cleat does not
> have"* until the buckets were enumerated, and then *"9 portable"* until the
> nine were audited against cleat's own surface — see *The 9 was 2* at the end of
> this section, which is the correction that matters, because the 9 was
> enumerated **and** machine-verified and was still wrong. The blocker table under *What blocks
> the 42* and the subsections below it are the **superseded** classification, kept
> because the reasoning in them is still the reasoning; read *The 17 does not
> reproduce* at the end of this section first. `docs/next-upstream.md` carries the
> same correction as an arrow (#114).

Count reconciled before classifying: **61 top-level test functions**, and **zero**
parametrize expansion, so the definition count equals the collection count here
and matches the inventory table's 61. Checked because the 44-vs-46 discrepancy on
`test_workflow_management.py` was entirely one `@parametrize`d case.

This said "61 by `def`" until the enumeration below was verified. `^def test_`
returns **56**: five of the cases are `async def`. The number was right and the
method named under it was not, which is the narrower version of the same problem
this section is now a correction to.

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

### The 17 does not reproduce — it is 9, enumerated

The bucket line above has been **rewritten**, not annotated: this is a reference
section, and a header stating a number the body then contradicts is worse than
either alone. The superseded line was

> 17 portable · 0 already covered · 2 answered differently on purpose · 42 need
> something cleat does not have

and `docs/next-upstream.md` carries the same correction as an arrow (#114),
where the arrow is right because that file is a summary a reader may have
already acted on.

**It survived because it was never enumerated.** Every other survey in this repo
was caught or confirmed by reconciling two derivations — 9c's two routes
disagreed on 5 of 33, and the `test_workflow_management.py` classifier bug
surfaced only because ISSUES 23 claimed a different total. A bare set of totals
offers nothing to disagree with, so nothing did.

**The superseded blocker table has the same shape of problem, and it is worth
stating because it is not an error.** Its rows sum to 44 (16 + 13 + 7 + 5 + 3)
against a stated 42 blocked. That is *consistent* with two cases carrying two
blockers each and being counted under both — which is what the table almost
certainly did — but the section never says which convention it used, so a reader
cannot tell a double-count from a miscount. The enumeration below adopts the
other convention and states it: **each case appears under exactly one bucket, so
the buckets partition the file and sum to 61.** Multi-blocker cases are named
explicitly underneath.

Re-derived from the same pin by classifying each case on the DBOS API its body
calls. **Collection and display are separate steps here, deliberately.** Every
applicable blocker was collected per case — not the first one matched, which is
the bug that mis-bucketed two cases in the `test_workflow_management.py` survey
— and each case is then *displayed* under one of them, so the buckets partition
the file. The cases carrying more than one are named after the sum:

**Portable — 9**

    test_child_workflow
    test_retrieve_workflow
    test_retrieve_workflow_in_workflow
    test_send_idempotency_key
    test_send_recv
    test_send_recv_temp_wf
    test_set_get_events
    test_simple_workflow_attempts_counter
    test_sleep

**`@DBOS.transaction` — SQL from inside a step — 12**

    test_child_workflow_assigned_id
    test_custom_database
    test_custom_names
    test_custom_schema
    test_debug_logging
    test_double_decoration
    test_duplicate_registration
    test_exception_workflow
    test_nonserializable_values
    test_start_workflow
    test_temp_workflow
    test_temp_workflow_errors

**An explicit recovery API — 11**

    test_duplicate_recovery_does_not_rerun_running_workflow
    test_recovery_appversion
    test_recovery_empty_id_dead_letters
    test_recovery_reenqueue_is_ownership_conditional
    test_recovery_temp_workflow
    test_recovery_thread
    test_recovery_workflow
    test_recovery_workflow_step
    test_workflow_returns_none
    test_workflow_timeout
    test_workflow_wrapped_by_custom_decorator

**Not an engine assertion — 10**

    test_custom_engine
    test_destroy
    test_destroy_semantics
    test_destroy_semantics_async
    test_eid_reset
    test_get_event_delivered_by_notifier_without_trigger
    test_notification_fallback_polling
    test_recv_wakeup_trigger_is_kept
    test_step_without_dbos
    test_timeout_cleanup_on_destroy

**`send_bulk` — 5**

    test_send_bulk
    test_send_bulk_duplicate_key_within_batch
    test_send_bulk_empty
    test_send_bulk_from_workflow
    test_send_bulk_idempotency_key

**`fork_workflow` — 4**

    test_get_event_timeout
    test_recv_timeout
    test_send_bulk_send_to_forks
    test_without_appdb

**Step introspection from inside a step — 3**

    test_run_step
    test_run_step_async
    test_simple_workflow

**Client-side select over handles — 3**

    test_wait_first
    test_wait_first_async
    test_wait_first_empty

**Enumerate a workflow's events (ISSUES 28) — 2**

    test_get_events
    test_multi_set_event

**Step listing with function names — 1**

    test_nested_steps

**An application-version registry — 1**

    test_app_version

**And the enumeration is machine-checkable against the pin, which is the whole
point of having one.** Verified 2026-09-09 against `dbos-inc/dbos-transact-py`
at `833794f7`, read in a scratch clone outside this repository:

```python
import ast, re
tree = ast.parse(open('tests/test_dbos.py').read())
real = {n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith('test_')}
listed = re.findall(r'^    (test_[A-Za-z0-9_]+)\s*$', open('WORKLIST.md').read(), re.M)
assert len(listed) == len(set(listed))   # no case listed twice
assert set(listed) == real               # no phantom, no omission
```

| | |
|---|---:|
| cases at the pin | 61 |
| names listed here | 61, all distinct |
| listed but not in the file | **0** |
| in the file but not listed | **0** |

**Use the AST, not a grep.** `^def test_` returns **56** here — five cases are
`async def` — so the obvious count is short by five and looks like a plausible
answer. `^\s*def test_` returns 121 and the AST finds 138 test-named functions
including nested ones, because inner fixtures are themselves called `test_step`
and `test_workflow`. Three readings, three numbers, one of which is the
collection count. That is the same denominator hazard this section's own header
paragraph flags for `@parametrize`, one level down.

Two classification claims were re-derived the same way rather than asserted:
**16 cases contain an `@DBOS.transaction`-decorated inner function** (matching
the superseded table's 16 exactly, from a different route), and all **10**
not-an-engine-assertion cases do reference DBOS internals — `_sys_db`,
`DBOS.destroy`, `_timeout_tasks`, `_registry`, `dbos_notifications_trigger` —
with none unaccounted for.

**Sum: 9 + 12 + 11 + 10 + 5 + 4 + 3 + 3 + 2 + 1 + 1 = 61**, which is the file's
case count by `def` and matches the inventory table. The partition is the check;
the individual bucket sizes are not independently verified against anything.
Cases carrying more than one blocker are listed under the first; `test_simple_workflow`,
`test_without_appdb` and `test_get_event_timeout` each carry two.

**Two corrections to the original numbers, in opposite directions.**

**Portable is 9, not 17.** Six of the eight I lost are cases whose *subject* is a
capability the survey did not screen for: `wait_first` (3 — a client-side select
over arbitrary handles, which `cleat_await_any_child` does **not** cover, because
it is a host call inside a workflow and only over children), step introspection
from inside a step (`DBOS.step_status`, `step_id` — 3). The other two enumerate a
workflow's events and belong to ISSUES 28.

**Ten cases are not engine assertions at all, where the original recorded none.**
This is the `test_client.py` pattern ws3 found. They assert on DBOS's own
implementation: that a Postgres trigger named `dbos_notifications_trigger` exists
(`test_recv_wakeup_trigger_is_kept`) or has been dropped
(`test_get_event_delivered_by_notifier_without_trigger`); that `recv` still works
when LISTEN/NOTIFY falls back to polling; that `DBOS.destroy()` then
`DBOS.launch()` leaves the library usable; that `len(dbos._timeout_tasks) == 0`;
that a caller-supplied SQLAlchemy engine is the one used. No engine can be
right or wrong about any of these. Filing them as gaps inflates the number
against nothing.

**16 cases use `@DBOS.transaction`, confirming the original's count of the
workflow-side gap exactly** — that number was independently re-derived and holds.
12 of them have it as their *first* blocker above; the other 4 carry it alongside
another.

### Validation of the re-derivation

Each case name announces a subject, so the classifier can be checked against it.
Eight cases were flagged where the name and the bucket disagree:

| case | name announces | classified | verdict |
|---|---|---|---|
| `test_get_event_timeout` | event timeout | needs fork | classifier right |
| `test_recv_timeout` | recv timeout | needs fork | classifier right |
| `test_without_appdb` | no app database | needs fork + txn | classifier right |
| `test_workflow_returns_none` | return value | needs recovery API | classifier right |
| `test_exception_workflow` | exceptions | needs txn | classifier right |
| `test_simple_workflow` | nothing specific | step introspection + txn | classifier right |
| `test_start_workflow` | starting | needs txn | classifier right |
| `test_workflow_timeout` | timeouts | needs recovery API | classifier right |

**Eight flagged, zero real** — these cases genuinely call `fork_workflow`,
`_recover_pending_workflows` or `DBOS.sql_session` while being named for
something else. Upstream frequently tests a timeout *by forking*.

That is the opposite outcome from the `test_workflow_management.py` section,
where the name check passed and the error was found by reconciling against an
independent count. **Neither check subsumes the other**, and the count
reconciliation is the one that has now caught a real error; here there was no
second count to reconcile against, because the 17 was never enumerated.

### What this section cannot settle

`test_nested_steps` asserts `list_workflow_steps` returns one entry carrying a
`function_name`. cleat's nearest surface is `GET /api/workflows/:id/history`,
which is an **event** log (`CountEventHistory`, `cmd/cleat-worker/server.go:1139`)
rather than a step list. Whether that answers the assertion is a judgement this
survey did not make; it is filed as blocked, and it is the single
lowest-confidence call in the table. Anyone reopening it should start there.

`test_simple_workflow_attempts_counter` is filed as portable on the strength of
cleat having `generation` and `reclaim_count`, which is a claim about
availability rather than about equivalence of meaning. Read the case before
porting it.


### The 9 was 2 — enumeration is not classification

The nine above were listed by name and the list was machine-checked against the
pin: 61 cases, exact partition, no phantom, no omission. **That check proved a
claim about the upstream.** "Portable" is a claim about *cleat*, and it was
screened by scanning cleat's host-call export list — which answers *does cleat
have something in this area*, not *can a port assert this end to end*.

Audited case by case against cleat's surface and against this port's existing
tests. The check that settles each one is given, because the previous version's
failure was that its check was not written down beside its conclusion.

| case | verdict | what settles it |
|---|---|---|
| `test_send_recv` | **portable** (one part) | several signals to one workflow arriving in a defined order. Nothing in `test_signals.py` or `test_send.py` asserts ordering. |
| `test_simple_workflow_attempts_counter` | **portable** | expressible through the API rather than upstream's direct system-DB read: `reclaim_count`/`generation`, plus `started_at >= created_at` (cleat#1090, #1091). |
| `test_child_workflow` | needs something cleat lacks → **now fixed upstream of us** | the parentage link. `workflow_instances.parent_workflow_id` was written on every child and in no `GetWorkflowByID` SELECT, so no client could read it. Filed as cleat#1103 and fixed; portable once that ships. |
| `test_retrieve_workflow_in_workflow` | needs something cleat lacks | reads an *arbitrary* workflow's status from **inside** a workflow. `cleat_poll_child` and `cleat_await_child` are the only guest-side cross-workflow reads and both are **children only**. ISSUES 33. |
| `test_send_idempotency_key` | needs something cleat lacks | `cleat_signal_workflow(target, signal, payload)` — three arguments, no idempotency key. ISSUES 34. |
| `test_send_recv_temp_wf` | needs something cleat lacks | its send/recv half is covered; its subject is `list_workflows` with id-prefix and start-time filters, and `WorkflowFilter` is `{Status, InputContains, ErrorContains, Search, Offset, Limit}`. ISSUES 35. |
| `test_sleep` | already covered | duration asserted in `test_complex_args.py:72` and `test_replay.py:76`. Its `sleep_counter == 1` is **not** replay — it is idempotent re-start by workflow id, which is `test_queues.py::test_the_same_idempotency_key_starts_one_run`. |
| `test_retrieve_workflow` | already covered | `test_api_surface.py::test_an_unknown_run_is_a_clean_404_on_every_read_path`. |
| `test_set_get_events` | already covered | the missing-key case is in `test_query_state.py`; the rest of the case iterates `use_listen_notify`, which is DBOS's own notification mechanism rather than an engine claim. |

**Why `test_child_workflow` is the instructive one.** `cleat_poll_child` looks
like it answers "whose child is this" and does not — it is children-only, read
from the parent's side. That is the same near-miss as `cleat_await_any_child`
against `wait_first`, which *this survey caught*, one case earlier. Catching a
trap does not inoculate against it; the check has to be run per case.

**The rule this adds to the three above: name which proposition each check
establishes.** Enumeration against the pin and portability against cleat are
different claims requiring different evidence, and satisfying the first says
nothing about the second. Both shipped in one sentence and only one had been
checked.
