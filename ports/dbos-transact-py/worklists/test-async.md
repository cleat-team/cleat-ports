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
