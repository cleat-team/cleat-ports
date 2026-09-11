# durabletask-go

Ports of [microsoft/durabletask-go](https://github.com/microsoft/durabletask-go)'s
assertions, re-expressed against cleat. Upstream source is not vendored; see
`UPSTREAM` for the pin and `../../docs/licensing.md` for why.

## What is here

| test module | cases | answering |
|---|---:|---|
| `orchestrations_test.go` | 2 | `tests/orchestrations_test.go` — an orchestration with no work completes; one whose only step is a durable timer resumes after it |
| `reuse_id_test.go` | 2 | `tests/orchestrations_test.go` — `Test_SingleActivity_ReuseInstanceIDIgnore`: a deduplicated start keeps the first run's input and its `created_at` |
| `purge_test.go` | 1 | `tests/backend_test.go` — `Test_PurgeOrchestrationState`: a purged run is gone from the read path, and repeating the purge is a clean no-op |

**These two exist to establish the harness.** They are the simplest assertions
upstream makes, chosen because a first port has to prove the whole path — build
a WASM workflow, deploy it, start it, read its terminal row — before anything
subtle is worth writing. The scoping below is the actual work product of this
PR; the tests are its proof of life.

### What `purge_test.go` could not port, and why that is written down

Upstream's `Test_PurgeOrchestrationState` makes four assertions. Two port
directly, one becomes a weaker true statement, and one cannot be expressed from
outside cleat at all.

| upstream assertion | here |
|---|---|
| purge succeeds | the sweep answers 200 |
| metadata is `ErrInstanceNotFound` afterwards | the run reads 404 |
| the runtime state holds **zero events** | **not portable — see below** |
| purging again is `ErrInstanceNotFound` | a second sweep is a clean no-op, not an error |

**The history assertion has nowhere to stand.** `/api/workflows/{id}/events` and
`/api/instances/{id}/history` both answer 404 while the run plainly exists — the
DBOS port recorded that before this one was written — and cleat deletes a
done/failed run's `event_history` at **finalize** time in
`finalize_workflow_status`, which `--retention-days`' own flag help states. So by
the time a run is sweepable there is nothing for the sweep to remove and nothing
outside the engine that could observe it either way.

The first draft asserted a 404 on those paths after the sweep. Its precondition
caught it: they 404 **before** the sweep too, so the assertion would have held
with retention switched off entirely. That is recorded in the test rather than
quietly deleted, because a check that passes for a reason unrelated to its
subject is the failure this suite exists to find. The engine-side coverage for
the history half is cleat#1265's test, which reads the tables directly.

**cleat has no per-instance purge.** Upstream takes an instance id; cleat's
equivalent is a retention sweep over everything past a window
(`POST /api/admin/retention/sweep`), so the test asserts the same postconditions
about one run without being able to name it in the request. That makes the sweep
destructive of other completed runs in the same database — safe here only
because this port declares no `t.Parallel()` and every test settles its own run
before the next begins, which was checked rather than assumed.

**Retention has to be switched on for any of this to be reachable.**
`--completed-workflow-retention-days` defaults to 0, which disables the arm, and
an `older_than` override deliberately does not enable an arm the configuration
turned off. `scripts/env.sh` now sets it through
`CLEAT_PORTS_WORKER_EXTRA_FLAGS`. One day is the smallest value that stays inert
by accident: the periodic sweep runs on a 24h interval and reaches nothing a test
creates, so only an explicit `older_than` touches a recent run. If a caller
overrides that variable the arm goes back to disabled, and the test then fails
naming the **configuration** rather than the engine — the sweep response reports
skipped arms separately from zero counts precisely so that distinction survives.

## The constraint that decides what is portable here

`go.mod` is stdlib-only and this port does **not import cleat**, inherited from
`ports/samples-go`. That is load-bearing rather than stylistic.

Upstream's suite has three parts, and the second is the reason the rule matters:

| upstream file | cases | shape |
|---|---:|---|
| `tests/orchestrations_test.go` | 26 | end-to-end through a task hub |
| `tests/backend_test.go` | 10 | the **backend contract**, driven directly |
| `tests/runtimestate_test.go` | 10 | a replay state machine, driven directly |

The backend-contract cases have a tempting cleat analogue at the **store**
level — `engine.NewPostgresStore` is exported, so this module could open a
database and drive `ClaimWorkflow` and `ReleaseWorkflow` itself. Doing that
would make this port a unit test of engine internals wearing a port's name, and
a failure in it would no longer distinguish "the engine is wrong" from "the
test drove it wrongly".

So a backend-contract case is portable here only if it has an **HTTP- or
harness-reachable analogue**. That is a stricter test than "cleat has something
in this area", and two cases already fail it — see below.

## In progress

**`Test_SingleSubOrchestrator_Failed` — ported; it found cleat#1115 (ISSUES 2).
`_Failed_Retries` — declined, see below.** Claimed here rather than announced elsewhere,
because two sessions ported the same upstream case tonight by each assuming the
other had not.

They came out of ports#145's re-check of the twelve cases classed as already
asserted by the dbos port. **Nothing in that port has a child that fails**: all
five cases in `test_children.py` use successful children, and its only
error-shaped assertion is `assert not r.get("error")` — the *absence* of one.
Upstream asserts the opposite direction, that a failed child's message reaches
the parent's failure details, and the `_Retries` variant asserts it after the
child exhausts a retry policy.

### `Test_SingleSubOrchestrator_Failed_Retries` — needs something cleat lacks

Upstream's variant attaches a **retry policy to the sub-orchestration** and
asserts the same failure propagation after the child exhausts it. cleat has no
per-child retry policy:

```go
type ChildWorkflowOptions struct {
    Version           int
    ParentClosePolicy ParentClosePolicy
    Priority          int
}
```

and the only retry export is `cleat_call_retry`, whose signature is
`(svc, op, req, maxAttempts, initialIntervalMs, backoffCoefficient100x,
maxIntervalMs, ...)` — a **service-call** retry, not a child-workflow one.
Re-derive with `grep -oE '\.Export\("[^"]+"\)' engine/imports.go | grep -i retry`.

Stripped of the retry policy the case is `Test_SingleSubOrchestrator_Failed`,
which is ported above, so porting it would add a second copy of one assertion
under a name claiming another.

**`Test_TerminateOrchestration_Recursive_TerminateCompletedSubOrchestration` —
ported.**

Claimed here rather than in `docs/durabletask-go-orchestrations-survey.md`,
which is the agreed place, because two PRs (#140, #148) currently have that file
open and a third writer guarantees a conflict for one of them. The purpose of
claiming is that another session can see it before starting; this file is as
visible and is the port's own.

**Two mappings this case needs, both checked against cleat rather than assumed.**

*Recursion is decided at a different time.* Upstream passes
`WithRecursiveTerminate(recurse)` at **terminate** time and parametrises over
both values. cleat decides per child at **spawn** time, via
`ChildWorkflowOptions.ParentClosePolicy` — so upstream's `recurse=true` maps to
a child spawned `TERMINATE`, and `recurse=false` to one spawned `ABANDON`, which
is cleat's default. The parametrisation ports; the flag does not.

*There is no terminate route.* The per-run verbs are `allowed-signals cancel dag
disable enable history promises query retry routing signal start tags terminal
update`. `enforceParentClosePolicy` fires when the parent **closes** — completes
or fails — so the port drives it by letting the parent finish rather than by
terminating it. Same predicate, reached the way this engine reaches it.


## Cases examined first-hand, and what each check established

Named because a survey of upstream establishes what **upstream** asserts; it
cannot establish what is portable **here**. Each row below was checked against
cleat, not against the upstream file.

### `Test_AbandonOrchestrationWorkItem` — reachable, but not the way it reads

Upstream abandons a claimed work item and asserts it can be **fetched again
immediately**. The claim is re-availability, not accounting.

cleat's analogue is `ReleaseWorkflow`, which has exactly three callers in
`cmd/cleat-worker/setup.go`: draining, DB-down-loading-history, and
DB-down-finalizing. The harness can produce the first — `scripts/worker.sh
stop` sends SIGTERM, `scripts/worker.sh crash` sends `kill -9` — so *released*
and *the owner died* are both producible.

**Not yet ported, and the obstacle has moved.** A workflow is only claimed
while a segment is executing; a durable sleep suspends and releases, so a
sleeping run is not held by anyone and draining releases nothing. Catching a run
mid-segment needs the fixture service to be able to block a call.

The sentence that stood here said it could not — "`scripts/fixture-service.py`
has no delay". That was **already false when it was written**: `delay_ms` landed
in #127 at 21:57 and this file claimed its absence in #135 at 23:24, 87 minutes
later. Both were the same session's, an hour and a half apart. A blocker is a
statement about the tree at a moment, and this one was copied forward from
before the tree changed under it.

What a fixed delay does *not* solve is the part the last sentence got right: a
delay gives a window of known length but says nothing about when the call
arrived, so the test still times its move against a duration. That is a race
with a comfortable margin, and margins are what a loaded runner removes.

`GET /inflight/<key>` and `POST /release/<key>` close it. The test waits until
the fixture reports the call is in the handler *now*, acts while it provably is,
and then releases:

    start the run, whose step calls the fixture with delay_ms
    poll GET /inflight/<key> until it reports 1     <- provably mid-segment
    scripts/worker.sh stop                          <- the drain under test
    POST /release/<key>

**It was then built and run, and it does not work — for a reason further in.**
Measured 2026-09-10 with exactly the sequence above:

    reclaim_count after `worker.sh stop` mid-hold:  1   (want 0)
    elapsed to completion:                         34s  (the reaper, not a re-claim)

**A draining worker waits for in-flight work; it does not release it.**
`cmd/cleat-worker/setup.go:1202` says so directly — on a cancelled context *or*
a drain the loop stops claiming "and wait[s] for in-flight workflows to finish
so events can be flushed cleanly". SIGTERM reaches that path: the handler
cancels the context and the loop sets `draining` itself.

So the rendezvous is exact and puts the run in precisely the state the release
path excludes. `releaseWorkflow`'s drain caller (`setup.go:1387`) hands back a
batch that was **claimed and not yet executed** — a TOCTOU guard for work
claimed in the window between the drain check and the claim returning.

**And there is a drain route, which does not help.** `POST /api/admin/drain`
(`server.go:225`) sets the same flag, so the *state* is producible over HTTP.
But a draining worker stops claiming, so draining first and starting work second
cannot reach `:1387` either. The route makes the state producible and the race no
more producible than before.

`worker.sh stop_worker` also sends SIGTERM, waits 5s, then SIGKILL, so a hold
longer than 5s ends in a kill and one shorter lets the segment finish with
nothing left to release. Both ends of the range miss.

**So this case is not portable**, and the second-worker machinery above is not
the missing piece — nothing gets released for a second worker to pick up. The
test and its fixture were written, run, and removed rather than skipped: a
skipped test whose subject is unreachable asserts nothing and reads as work in
progress.


**A cleat-specific observation worth keeping separate from the port.**
`ReleaseWorkflow`'s UPDATE does not touch `reclaim_count`; the reaper's does
(`reclaim_count = reclaim_count + 1`, all three dialects). So the two paths are
distinguishable on the row. That is a real assertion and it is **not** this
upstream case's claim — recording it as one would be attributing a cleat
question to durabletask-go.

### `Test_ScheduleActivityTasks` / `ErrNoWorkItems` — expressible, not portable

Upstream requires an empty queue to be distinguishable from an error.

cleat does distinguish them: `ClaimWorkflow` returns `(nil, nil)` for an empty
queue and `(nil, err)` for a failure. But that is a **store-level** distinction
and an idle worker returning no work is not an observable HTTP event, so it
fails the reachability rule above.

*Expressible in cleat* and *portable here* are different verdicts. This one is
the first and not the second.

### `tests/runtimestate_test.go` — unclassified, deliberately

Whether cleat's event history exposes a seam equivalent to upstream's replay
state machine is not established by reading upstream, and it has not been
checked here. No portable figure is quoted for this file.

## Changing a fixture is not enough to change what runs

Two layers cache, and both produced a **wrong falsification** before being
found — a mutation reported as having no effect, when it had never been
applied.

**A redeploy does not replace the workflow bytes.** `deploy-workflow` is
idempotent by `(name, version)`. Editing a fixture and re-running leaves the
previous WASM in `workflow_defs`, and the test exercises the old code while the
source on disk shows the new. Verified rather than guessed: after editing a
child's `ParentClosePolicy` from TERMINATE to ABANDON and re-running, the new
run's rows still read

```sql
SELECT parent_close_policy FROM workflow_instances WHERE def_name = 'dtg_terminate_leaf';
-- TERMINATE
```

and `workflow_defs` still held one row, version 1, created by the first run.

**`worker.sh ensure` reuses a running worker.** Rebuilding `bin/cleat-worker`
changes nothing until the process is restarted, and `ensure` on a live worker is
a no-op that prints a port-in-use hint rather than an error. Compare the binary's
mtime against `ps -p "$(cat .port-results/<project>/worker.pid)" -o lstart=`,
and check the pid actually changes across a `stop`/`ensure`.

**So a falsification here has three layers to get wrong**, and each fails
silently in the reassuring direction: the source changed, the artifact did not;
the artifact changed, the process did not; the process changed, the assertion
was never sensitive to it. Assert the mutation applied *at the layer the test
reads*, not at the one you edited.

## Two things learned building this, recorded because they cost time

**A single non-`HostCalls` parameter receives the whole input JSON, not the
named field.** `HandleEmptyOrch(h, marker string)` started with
`{"marker":"x"}` binds `marker` to the literal text `{"marker":"x"}`. Adding a
second parameter, or taking a struct, binds by name. This is deliberate — it is
how a workflow takes an opaque payload it parses itself — and it is documented
as W003 in `docs/workflow-go-constraints.md` in cleat.

**The toolchain says so at build time, and this harness swallows it.**
`scripts/build-workflow.sh` emits

```
Warning: HandleEmptyOrch:17: ... whose only parameter is a single string, so
"marker" receives the ENTIRE input JSON rather than the field of that name.
[W003]
```

`deploy()` in `harness_test.go` captures the build output and surfaces it only
when the build **fails**. A warning on a successful build is therefore
invisible, and the failure it predicts arrives later wearing a different name:
here it was a result stored as `{}`, because the unquoted JSON object spliced
into a JSON string produced invalid JSON, which cleat replaces with `{}`
(cleat#1024). Two layers between the warning and the symptom.

That was nearly filed as a cleat defect — *"a workflow with no host calls loses
its result"* — on the strength of one contrast that had **two** variables in it.
Changing one at a time gave the real answer, and the toolchain had already given
it before the first run.

`deploy()` now surfaces them. It reads the toolchain's stderr on a **successful**
build too, not only through `*exec.ExitError` on a failed one, and reports what
it finds with `t.Logf` -- which Go prints whenever the test fails, putting the
prediction in front of whoever is reading the failure it predicted. The same
change is in `ports/samples-go` and in the Python harness.

Two of the warnings are filtered out, and that is the other half of why W003 was
missed. `cleat_complete` and `cleat_poll_work` are reported as orphaned imports
on **every build of every workflow**, including one that makes no host calls at
all -- cleat's generator emits both unconditionally while its scanner compares
them against the workflow's closure, which they are never in. So even a surfaced
W003 would have arrived third in a list whose first two entries are always
wrong. Filed as cleat#1125; the suppressed count is reported rather than hidden,
so when it is fixed the filter goes inert instead of stale.

## Not a coverage ratio

The counts above are cases **ported**, against cases upstream **has**. They are
not a percentage of anything: several upstream cases probe decisions cleat has
made differently on purpose, which is a finding rather than a gap. Those go in
`ISSUES.md` as they are established; entry 1 is there already — cleat has no
operator-level suspend, which upstream's `Test_SuspendResumeOrchestration`
requires and which cleat's engine-driven suspend is not a substitute for.
