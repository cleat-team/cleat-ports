# durabletask-go

Ports of [microsoft/durabletask-go](https://github.com/microsoft/durabletask-go)'s
assertions, re-expressed against cleat. Upstream source is not vendored; see
`UPSTREAM` for the pin and `../../docs/licensing.md` for why.

## What is here

| test module | cases | answering |
|---|---:|---|
| `orchestrations_test.go` | 2 | `tests/orchestrations_test.go` — an orchestration with no work completes; one whose only step is a durable timer resumes after it |

**These two exist to establish the harness.** They are the simplest assertions
upstream makes, chosen because a first port has to prove the whole path — build
a WASM workflow, deploy it, start it, read its terminal row — before anything
subtle is worth writing. The scoping below is the actual work product of this
PR; the tests are its proof of life.

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

So the remaining work is the port itself, not the harness. Proving *re-claimed*
rather than merely *released* needs a second worker to pick the run up, and the
harness already has one: `CLEAT_PORTS_WORKER_INSTANCE` gives each instance its
own API port, pidfile and log, and `scripts/worker.sh` says in as many words
that it exists "so cross-worker cases are expressible at all".

The first draft of this paragraph said the harness ran only one, in the same
edit that corrected the delay claim above. Checked before committing, which is
the only reason it is not a second stale blocker in the file that exists to
retire the first.

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

Surfacing build warnings from `deploy()` is worth doing and is not in this PR;
it changes shared harness behaviour for every port and belongs on its own.

## Not a coverage ratio

The counts above are cases **ported**, against cases upstream **has**. They are
not a percentage of anything: several upstream cases probe decisions cleat has
made differently on purpose, which is a finding rather than a gap. Those go in
`ISSUES.md` as they are established; entry 1 is there already — cleat has no
operator-level suspend, which upstream's `Test_SuspendResumeOrchestration`
requires and which cleat's engine-driven suspend is not a substitute for.
