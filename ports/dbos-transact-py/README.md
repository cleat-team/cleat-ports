# dbos-transact-py

Port of [DBOS Transact (Python)](https://github.com/dbos-inc/dbos-transact-py)'s
test suite onto cleat's Python SDK. See [`UPSTREAM`](UPSTREAM) for the pinned
upstream commit.

## Why this upstream first

DBOS is the closest architectural match to cleat in the ecosystem: durable
execution backed by your own PostgreSQL, with no separate stateful service. Its
tests therefore assert the things cleat's design actually stakes out — queue
concurrency limits, recovery counts after a crash, deduplication and idempotency,
cron scheduling, schema migration — rather than the behaviour of a workflow
service cleat does not have.

It is also MIT licensed, which makes it portable here without friction, and
Python is a tier-1 language in cleat's `tiers.yaml`, so failures land on ground
cleat claims to hold rather than on a known gap.

## Upstream test inventory

Counts are the cases pytest collects from the pinned upstream commit — `test_*`
at module scope or in a `Test*` class. A bare `def test_*` count is wrong: DBOS
defines workflows and steps *inside* test bodies with names like `test_step` and
`test_workflow`, which inflates `test_queue.py` from 77 to 103. Re-run with
`scripts/count-queue-cases.py`, which documents the method and its caveats.

Priority reflects how much each file says about an *engine* as opposed to an
application or a web framework.

| Upstream file | Cases | Priority |
|---|---:|---|
| `tests/test_queue.py` | 91 | **1** — concurrency limits, rate limits, dedup, priority |
| `tests/test_failures.py` | 37 | **1** — retries, error classification, recovery |
| `tests/test_workflow_management.py` | 46 | **1** — cancel, resume, fork, list, delete |
| `tests/test_concurrency.py` | 11 | **1** — concurrent execution and isolation |
| `tests/test_dbos.py` | 61 | 2 — broad core surface, mixed with SDK ergonomics |
| `tests/test_async.py` | 33 | 3 — a third of it asserts nothing about an engine; read case by case, 1 is portable. See the note below |
| `tests/test_scheduler.py` | 35 | 2 — cron and scheduled workflows |
| `tests/test_client.py` | 57 | 3 — client API surface, largely DBOS-specific |

**Both tables are generated, and CI checks the file still matches the tree.**

    python3 scripts/count-queue-cases.py --inventory   # print them
    python3 scripts/count-queue-cases.py --check       # fail if README has drifted

`Cases` is measured by **collection** — what pytest would actually run — at the
pinned upstream ref, not by grep. Every figure this table carried before was
`grep -c 'def test_'`, which counts helper functions defined *inside* test
bodies; DBOS tests declare their workflows and steps locally and name them
`test_workflow`, `test_step`, `test_child_wf`. That method reproduces all eight
old values exactly, which is how it was identified rather than guessed:

| upstream file | was (grep) | functions | **cases** |
|---|---:|---:|---:|
| `test_dbos.py` | 138 | 61 | **61** |
| `test_queue.py` | 103 | 77 | **91** |
| `test_async.py` | 57 | 32 | **33** |
| `test_concurrency.py` | 5 (1 skipped) | `test_queue.py` — concurrency keys are cleat's dedup surface |
| `test_failures.py` | 43 | 37 | **37** |
| `test_workflow_management.py` | 5 | `test_workflow_management.py` — force-complete, force-fail, and their refusals |
| `test_scheduler.py` | 35 | 35 | **35** |
| `test_client.py` | 54 | 54 | **57** |

**Two corrections are in play and they run in opposite directions**, which is
why no single story explains the column. Unanchored grep counts inner helpers
that pytest never collects, which pushed figures *up*. A parametrized function
is one definition and several collected cases, which pushes them *down* if you
count definitions — `@parametrize("code", [400, 401, 403, 404])` is four cases.

`Cases` is the last column: what pytest collects, both effects applied.

**`test_queue.py`'s 77 was believed verified and was not.** It is the figure
this whole correction was anchored on, corrected once already in #51 from 103,
and cited as the one row counted by collection rather than by grep. It is 91:
77 is its function count, and three parametrize decorators expand it. A number
that has already been corrected once reads as settled, and this one was carried
forward by three sessions without being re-derived.

**Four rows are unchanged from the grep figure**, which is why the old numbers
looked plausible for so long: inner helpers appear only in files that declare
workflows locally, and parametrize only in four files. A method that is right
on half the corpus is the hardest kind to doubt.

**An anchored `grep -cE '^(async )?def test_'` also gives the right answer on
all eight, and should still not be used.** It excludes inner helpers only
because they are indented, and it cannot see a `test_` method on a `Test*`
class at all. No upstream file here has one (`grep -cE '^class Test'` → 0
across all eight), so the agreement is a property of these files rather than of
the method, and it fails silently in the flattering direction the day one
appears. Collection asks the question directly.

`Ported` is collected live from `tests/`. It used to be hand-maintained, and
gave three different answers at once — cells summing to 74, a stated total of
79, and 82 in the tree. The mapping from our modules to upstream files is
judgement and still lives in one reviewable place, `MAPPING` in
`scripts/count-queue-cases.py`; the counts beside it no longer are. A module
added to `tests/` and not to `MAPPING` fails the check rather than being
silently omitted, which is how four modules went missing from the second table.

**A skipped case is not coverage**, so the second table marks them and the
figure is derived rather than written down — the note this replaces said
"9 active and 1 skipped" against a cell that had since moved to 12.

Only cases skipped **outright**, by decorator, are counted. A conditional
`pytest.skip()` inside a body is not: those are written to skip on a known
defect and assert in full otherwise, so one becomes a passing case the day the
defect is fixed, with nobody editing it. `test_dead_letters.py` has exactly one
and it started passing when cleat#979 was fixed. Counting it as a skip would
understate coverage and go stale silently, which is the failure this whole
section exists to stop.

### `tests/test_async.py` is priority 3, and the reason is not the one given here until now

Read case by case at `833794f7` — the full partition, with every case named, is
in `WORKLIST.md`. **The priority-3 conclusion holds. The reason recorded here for
three sessions did not survive the reading.**

This section used to say the file was *"mostly the async mirror of assertions
this port already makes in sync form"*, at `~23` of 33. The mirror bucket is
**11**. What the section had at `~6` — "Python event-loop specifics" — is **11**,
and it is a stronger reason to skip the file than redundancy: those cases assert
properties of the Python SDK's own async machinery (its notification maps, its
poll loop, which event loop a coroutine runs on, whether `destroy()` deadlocks).
Every one would still be a valid test of `dbos` if its storage layer were
replaced, so there is no engine claim in them to port.

| | |
|---:|---|
| 11 | **not an engine assertion at all** — the SDK's own async machinery |
| 11 | the **async mirror** of assertions this port already makes, each mapped to the local test that makes it |
| 9 | need something cleat does not have — all of it already recorded: ISSUES 22 (5), 28 (1), 25 (1), bulk send (1), the `RunDetached` handle gap (1) |
| 1 | answered differently on purpose — this port cannot make it false |
| 1 | **portable** — `test_max_parallel_workflows` |

**The one portable case is not an async assertion.** It asserts 50 workflows
complete in wall-clock time that serial execution could not achieve, and
**nothing in this port asserts that workflows run in parallel at all.** The
closest, `test_concurrency.py::test_distinct_keys_do_not_block_each_other`,
asserts both starts are admitted and both complete — which a worker running them
one after another satisfies. So the file's single useful case is one the *sync*
suite does not make either.

The reasoning that survives is the part about this port's shape: **the `async`
that makes these cases distinct upstream has no counterpart on our side to be
distinct about**, because this port drives cleat over HTTP and its workflows are
Go compiled to WASM.

(Two corrections. This section said "of its 32 cases" while the generated table
above said 33 — `test_async_wait_does_not_recheck_past_its_deadline` is
parametrized over `["get_event", "recv"]`, so 32 functions collect as 33 cases.
That is the definitions-versus-cases distinction documented two sections above
the place that got it wrong. And an earlier assessment attributed 29 of these to
**PY012**, `python-sdk`'s refusal of `async def` entry points — real, and a
future Python-SDK port would meet it, but it cannot apply to a port with 34 Go
workflow files, 0 Python ones, and no import of `cleat_sdk` anywhere. Retracted
before it reached the table.)

## What this suite structurally cannot catch

Distinct from the section below, which lists cases nobody has ported. These are
classes of defect that **no test added to this suite would find**, because the
harness cannot express them. They are worth stating because a coverage figure
invites the reading that what is not listed as a gap is covered.

**One tenant.** The harness authenticates with a single API key for a single
tenant (`scripts/worker.sh`'s `mint_key`, `CLEAT_PORTS_API_KEY`). Every
cross-tenant isolation property is therefore invisible here, in either
direction — a leak and an over-restriction look identical to a suite that only
ever holds one tenant's data.

This is not hypothetical. cleat#1017: the `idempotency_keys` outcome writes were
tenant-scoped on PostgreSQL and on neither MySQL nor SQL Server, so completing a
workflow overwrote every tenant's idempotency row naming that `workflow_id`. It
survived because the engine's own regression test was hardcoded to one dialect,
and this suite could not have caught it at any level of coverage. The bound is
better than it sounds — `idempotency_keys` was the **only** table with a
`tenant_id` and no row-level security behind it, so the class has one member —
but the blind spot is permanent until the harness grows a second tenant.

**One worker, and it is also the API server — no longer, but read on.** A
`second_worker` fixture now starts a second `cleat-worker` against the same
database, sharing its API key and fixture service, so the cross-process cases
below are reachable; `tests/test_cross_worker.py` uses it. What remains true is
the shape: one process serves the API *and* runs workflows, so stopping a worker
to simulate an outage still stops an API, and nothing can be observed through
the worker you just stopped. The cases this used to make unreachable were:

- a stale-but-living run writing its outcome after another worker took over
  (upstream `test_workflow_outcome_is_owned_by_the_pending_row`; cleat answers it
  with a generation fence, see `ISSUES.md` #21)
- a concurrency key genuinely contended across processes rather than serialised
  within one
- a signal delivered to a workflow owned by a different worker

Stopping the worker to simulate the outage also stops the API, so nothing can be
observed *during* one — see `conftest.py`'s `worker.stop()` docstring, which had
this wrong until 2026-09-08 and described a deployment shape this harness does
not have.

**Timing floors set by the engine, not by the tests.** Recovery depends on a
heartbeat going stale and a reaper noticing, so recovery assertions cost 10-30s
each and their timeouts are engine constants rather than arbitrary. A test that
appears slow here is usually waiting on a real mechanism.

**What follows from all three:** absence from this suite is not evidence of
absence in cleat. The `Ported` column measures cases expressed against a
single-tenant, single-worker harness, and says nothing about the properties that
harness cannot state.

## What this port deliberately skips, and why

- `test_fastapi.py`, `test_flask.py`, `test_sqlalchemy.py` — web/ORM integration.
  Tests DBOS's framework adapters, not durable execution.
- `test_kafka.py` — DBOS's Kafka integration; cleat has no equivalent surface.
- `test_config.py`, `test_package.py`, `test_application_name.py`,
  `test_docker_secrets.py` — DBOS configuration and packaging.
- `test_croniter.py` — exercises the upstream's cron *library*, not the engine.
  The scheduling semantics worth porting live in `test_scheduler.py`.
- `test_cockroachdb.py`, `test_pgsql_client.py` — upstream-specific backends.
- `test_conductor_lifecycle.py`, `test_telemetry.py`, `test_admin_server.py` —
  DBOS Conductor and its observability stack.

### Cases left unported on purpose, with the reason

Whole-file skips are above. These are individual cases assessed and declined,
recorded so nobody re-derives them as oversights.

- `test_scheduler.py::test_dynamic_scheduler_add_after_launch` — **covered, with
  a known delta.** `test_scheduling.py::test_a_cron_schedule_actually_starts_its_workflow`
  already creates a schedule while the worker is running and asserts it fires.
  Upstream asserts it fires **twice**, which proves recurrence rather than a
  one-shot; ours asserts once. That is a real difference and it is declined on
  cost: cron granularity is a minute, so the second firing costs two more
  minutes of suite time for a claim the first firing makes most of.
- `test_scheduler.py::test_dynamic_scheduler_replace_schedule` — **measured, no
  defect to pin.** Delete-then-recreate under one name is clean in cleat:
  `DeleteSchedule` is a hard `DELETE`, the recreate inserts a fresh row, and the
  new input is used with no policy or timing state carried across. Probing this
  is what found cleat#995 and cleat#996, which are the results that came out of
  it.
- `test_failures.py::test_step_timeout_rejects_invalid_config` — **the premise
  does not exist here.** Upstream asserts three rejections and cleat can express
  none of them. *"only supported for async steps"*: a cleat workflow has no
  sync/async split. *"positive and finite"*, tested with `NaN` and `inf`:
  cleat's `Timeout` is a `time.Duration`, an int64, so **there is no input to
  reject**. `0`: a documented sentinel — `Timeout time.Duration // 0 = no
  timeout` (`cleat/runtime.go`) — so asserting it is rejected would contradict
  the contract rather than test it.

  The one expressible residue is a *negative* timeout, which cleat neither
  rejects nor honours. It is not writable yet either: while cleat#1006 leaves
  every timeout inert, a test cannot distinguish "negative is ignored" from
  "everything is ignored", so it would pass without separating the two and
  would go green the day #1006 is fixed while still proving nothing.
- `test_failures.py::test_step_timeout_inert_outside_workflow` — **no vantage
  point.** It calls a step outside a workflow. Cleat has a behaviour there —
  `DurableCall can only be called from within a workflow function` — but it is
  an error rather than inertness, and a port test drives the HTTP API, which
  can only start workflows. See *What the front door costs* below.
- `test_scheduler.py::test_long_schedule_shutdown` — parked. It wants the
  `worker.stop()` correction (that helper stops the API server and the fixture
  service too), and `test_misfire.py` already exercises the stop/restart path
  it would cover.

### What the front door costs

Every test here drives the HTTP API. That is what makes a port test hard to aim
at dead code: you reach production by construction, where an engine test that
calls a store method directly can pass against a path the worker never runs.

The same property is a limit. The API can only start workflows, so anything
upstream asserts about calling a step *outside* one has no vantage point from
here — not because cleat lacks the behaviour, but because nothing in the port's
reach can provoke it.

Worth stating in both directions, because the advantage is the reason to keep
using the front door and the limit is the reason some upstream cases will never
port. They are one property, not two.

## Status

**82 cases on `develop`**, re-derived 2026-09-08 with the command under the
inventory table. The figure this line carried until then — *"73 ported, 70
passing, 3 skipped"* — was produced by `grep -hcE '^def test_'`, the same
inflating method corrected above, and disagreed with both the table's total (79)
and the tree (82).

**The pass/skip split is deliberately not published here.** It is not a property
of this port: it depends on which cleat ref the suite runs against, and it moves
whenever a fix lands or a skip retires itself. Run the suite and read it from
there. The inventory above is the work plan;
the `Ported` column is the progress metric. Priority 1 first, and all four
priority-1 files are started.

This line said **"scaffolded — no tests ported yet"** in `ports/README.md` until
2026-09-07, by which point the port had 53 cases and had found 19 defects. A
status line is a claim with a date on it; this one had neither.

The `Ported` column counts cases in *this* suite that carry an upstream
assertion, mapped to the upstream file the assertion came from:

| This suite | Cases | Mapped to |
|---|---:|---|
| `test_api_surface.py` | 8 | `test_client.py` — the HTTP surface a client drives; two of its cases are arguably workflow-management |
| `test_cancellation.py` | 4 (1 skipped) | `test_workflow_management.py` |
| `test_children.py` | 5 | `test_concurrency.py` — concurrent execution and isolation |
| `test_complex_args.py` | 3 | `test_queue.py` — upstream test_complex_type -- a nested struct argument survives the store, including across a suspension |
| `test_concurrency.py` | 5 (1 skipped) | `test_queue.py` — concurrency keys are cleat's dedup surface |
| `test_continue_as_new.py` | 2 | `test_dbos.py` — bounded history via self-restart |
| `test_cross_worker.py` | 3 | none — cleat-specific: mutual exclusion across two worker PROCESSES, which needs the second_worker fixture and has no upstream analogue |
| `test_dead_letters.py` | 5 | `test_failures.py` — retries exhausted, and what is retained |
| `test_defer.py` | 3 | `test_dbos.py` — cleanup that runs once though the body runs twice |
| `test_detached.py` | 3 (1 skipped) | `test_workflow_management.py` — the nearest thing cleat has to fork |
| `test_determinism.py` | 4 | `test_dbos.py` — stable IDs and randomness under recovery |
| `test_executor_identity.py` | 1 (1 skipped) | `test_queue.py` — upstream test_queue_executor_id -- which worker ran a completed run; skipped, ISSUES.md 26 |
| `test_idempotency_key_form.py` | 5 | `test_client.py` — upstream test_client_enqueue_rejects_empty_workflow_id -- a blank identifier must not become a real one |
| `test_identity_isolation.py` | 1 | `test_concurrency.py` — a run reports its own id under concurrency |
| `test_locks.py` | 2 | `test_queue.py` — serialising work through a held key |
| `test_misfire.py` | 1 | `test_scheduler.py` — firings missed during an outage — upstream calls it backfill, cleat calls it misfire_policy |
| `test_parallelism.py` | 3 | `test_async.py` — the one portable case: workflows actually run at once |
| `test_plugins.py` | 2 | none — cleat has no upstream analogue; plugin calls through a real worker |
| `test_priority_order.py` | 2 | `test_queue.py` — priority is a queue control |
| `test_promise_wakes.py` | 2 | none — cleat-specific: does the promise wake path share cleat#953's defect |
| `test_promises.py` | 3 | `test_dbos.py` — `set_event`/`get_event` |
| `test_query_state.py` | 2 | `test_dbos.py` — workflow status readable while running |
| `test_queues.py` | 6 | `test_queue.py` — deduplication by Idempotency-Key, priority accepted |
| `test_recovery.py` | 4 | `test_failures.py` — recovery counts after a crash |
| `test_replay.py` | 2 | `test_dbos.py` |
| `test_results.py` | 5 | `test_failures.py` — upstream's test_nonserializable_return; the property generalises past pickle, and cleat substitutes rather than failing |
| `test_run_metadata.py` | 1 | `test_dbos.py` — a repeat start is deduplication rather than recovery, and the run's own clock is ordered |
| `test_retries.py` | 16 | `test_failures.py` |
| `test_schedule_timezones.py` | 3 | `test_scheduler.py` — cron zones and the default zone |
| `test_scheduling.py` | 13 | `test_scheduler.py` — cron and delayed invocation |
| `test_send.py` | 3 | `test_dbos.py` — `send` delivery semantics |
| `test_signals.py` | 4 | `test_dbos.py` — `recv` with a timeout, and `send` between workflows |
| `test_timeouts.py` | 1 (1 skipped) | `test_queue.py` — upstream test_unsetting_timeout -- a per-run deadline and whether a child inherits it; skipped, ISSUES.md 25 |
| `test_versions.py` | 3 | none — cleat-specific version reporting across a suspension |
| `test_workflow_management.py` | 5 | `test_workflow_management.py` — force-complete, force-fail, and their refusals |

The five skips are not unfinished work. Each is a cleat gap this port found,
left visible in the suite with the reason attached rather than deleted, so the
assertion a reader expects is where they expect it:

(This sentence said "three" while the table below listed four and the suite had
five. A count in prose beside the list it counts is a claim that rots twice —
derive it, or do not write it.)

| Skipped | Gap |
|---|---|
| `test_blocked_task_runs_after_the_holder_finishes` | no queueing concurrency limit; a blocked start is rejected rather than deferred |
| `test_a_detached_run_can_be_addressed_by_its_caller` | `RunDetached` returns no handle |
| `test_cancel_stops_a_workflow_that_does_not_cooperate` | no pre-emptive cancellation and no cancelled terminal state |
| `test_the_workflow_id_survives_the_transition` | continue-as-new starts an unlinked new run, so the caller cannot follow the chain to its result (cleat#826) |
| `test_polling_finds_nothing_before_a_signal_and_finds_it_after` | `PollSignal` is not replayed: it re-queries live, so the first poll re-answers `true` after a suspension (cleat#882) |

### What the port has found so far

Every defect below was reachable only by running a compiled workflow against a
real database. None was visible from reading cleat's source, and cleat's own
suite was green throughout.

| cleat issue | Defect |
|---|---|
| #776 / #804 | the durable clock stopped for the length of every sleep, and a replay read a different clock than the original execution |
| #799 / #806 | `DurableSend`, `ResolvePromise` and `RejectPromise` were unreachable from a Go workflow |
| #771 / #808 | `cleat build` dropped a project's own SDK replace and compiled against the module proxy |
| #811 | replay never advanced the checksum chain, so any workflow recording an event after resuming died with a checksum mismatch |
| #812 | the worker never wired the promise store, so every await hung forever and `workflow_promises` had never held a row |
| #827 | continue-as-new wrote a raw result into a JSON column, so the feature failed outright on PostgreSQL — `coerceResultJSON` was called from one write path out of three |
| #826 | a continue-as-new chain is unfollowable: the caller sees `{}` and nothing links to the successor |
| #824 | a single-string entry point silently receives the raw input JSON, and the failure names whatever the argument was later used for |
| #813 | a promise was keyed by its creator, so no other workflow could settle one — which is the only thing a promise is for |
| #814 | a promise await re-armed its deadline every wake, so its timeout never fired — generation 3130 for a 5s timeout, now 2 |
| #775, #777, #787, #796 | earlier findings from the same harness |

## Running

```bash
make -C ../.. deps
make -C ../.. install-cleat
make -C ../.. port PORT=dbos-transact-py
```

## Findings

See [`ISSUES.md`](ISSUES.md). Concept mapping to start from:
`docs/migration/from-dbos.md` in the core repo — and when a mapping there turns
out to be wrong, that is itself a finding.
