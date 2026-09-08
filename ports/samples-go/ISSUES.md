# samples-go: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

Empty is the correct starting state. Add entries as you port, not at the end.

---

## 1. Saga steps cannot be factored: the API is closure-based, the analyzer rejects closures

**Class:** Design difference (with a cost worth naming)
**Upstream sample:** `saga/`
**Status:** Open

**What upstream asserts**

Nothing about code shape — but the upstream sample factors its activity
invocations into a helper and calls it from each step, which is how anyone
would write a saga of more than three steps.

**What cleat does**

`cleat.Saga.AddStep` takes two function values, and `Run` calls them. So the
saga API is closure-based by construction. The workflow analyzer, however,
rejects any call through a function value:

```
E009: HandleSagaTransfer:51: function-value calls cannot be statically resolved;
      the analyzer cannot trace the call chain
      -> Replace with a direct function call or inline the logic.
```

Seven of these, from the natural factoring:

```go
forward := func(op string) func(cleat.HostCalls) (string, error) {
    return func(h cleat.HostCalls) (string, error) {
        return h.DurableCall("banking", op, bankReq(op, op == failAt))
    }
}
s.AddStep("withdraw", forward("Withdraw"), compensate("WithdrawCompensation"))
```

The two rules compose into a narrow lane: step bodies **may** be written as
literals at the `AddStep` call site, and **may not** be produced by anything.
A package-level `func` is fine to call *from inside* a literal; a local
`req := func(...)` is not, because calling it is a function-value call.

Note this is not a general ban on function values — `AddStep` receives them
and `Run` invokes them, inside the SDK, without complaint. The analyzer's
reach stops at the workflow package.

**Assessment**

The E009 rule is defensible on its own: an analyzer that cannot trace a call
chain cannot verify determinism, and guessing would be worse. What makes it a
finding is the *interaction*. cleat ships a saga helper whose entire interface
is function values, and then forbids the calling code from constructing them.
An N-step saga costs N copies of its call shape, and `workflows/saga/main.go`
in this port is deliberately left in that shape so the cost is visible rather
than hidden behind a comment.

The upstream sample cannot be ported as written. That is the finding.

---

## 2. `examples/saga-temporal-port/ISSUES.md` is stale on two of its six items

**Class:** Documentation defect in the core repo
**Upstream sample:** `saga/`
**Status:** Open

**What the core repo claims**

`examples/saga-temporal-port/ISSUES.md` #4:

> The `Saga.AddStep` compensate function signature is `func(HostCalls)` — it
> returns no error. This means compensation failures are silently dropped.

and #6, that `Run` wraps a failed step as `saga step %q failed: %w`.

**What cleat does**

Neither holds. `AddStep`'s third parameter is `func(HostCalls) error`, and
`Run` collects compensation failures with `errors.Join` and returns them
alongside the forward error (`cleat/runtime_workflow.go:426`). The wrapping is
`fmt.Errorf("saga: %w", ...)`.

Executed, not read: `TestAFailingCompensationIsReportedNotSwallowed` fails a
compensating call on purpose and asserts (a) the remaining compensations still
run, and (b) the run's error still names the forward failure. It passes.

**Assessment**

The findings were true when written and were never re-checked, which is what
happens to a finding recorded as prose next to code that keeps moving. Worth
noting *how* they went stale rather than just that they did: all six were
derived by reading the SDK source, so the document has no executable component
that could have failed when the signature changed.

The same drift is visible one layer down — the doc comment above `AddStep`
still shows its example compensator as:

```go
func(h HostCalls) {
    h.DurableCall("flights", "Cancel", cancelJSON)
}
```

which would not compile against the function it documents.

This is the argument for the ports repo over a design review: an assertion that
runs tells you when it stops being true.

---
## 3. A mis-cased `parent_close_policy` means different things on different dialects

**Class:** Bug (silent divergence) + validation gap
**Upstream sample:** `child-workflow/`
**Status:** Fixed — cleat-team/cleat#936, closed by #938 on 2026-09-08

**What upstream asserts**

Temporal's `ParentClosePolicy` is an enum. A value outside it cannot be sent —
the client rejects it — so "the policy I wrote is the policy that ran" is
guaranteed by construction rather than by care.

**What cleat does**

Two things, and they were only visible together.

*The validation gap.* `enforceParentClosePolicy` matches exact string literals
and ABANDON has no arm — it is the *absence* of an update — so an unrecognised
value silently means ABANDON. `ParentClosePolicy` is a `string` type, the typed
constants are trivial to bypass, and the column DEFAULTs to `'ABANDON'`, so a
wrong value and a missing one are indistinguishable afterwards.

*The divergence.* String equality is collation-dependent, and the dialects
disagree:

```
mysql>      SELECT 'terminate' = 'TERMINATE';   1     (utf8mb4_0900_ai_ci)
postgres=#  SELECT 'terminate' = 'TERMINATE';   f
```

Same workflow, same policy string, same test:

| dialect | child after the parent closes | effective policy |
|---|---|---|
| PostgreSQL | `done`, both calls made | ABANDON |
| MySQL | `failed`, only the first call | TERMINATE |

**Assessment**

The divergence is the serious half. A validation gap fails **open** in a
predictable direction; this produces *opposite* child-lifecycle behaviour from
identical code depending on the backing database, with nothing in the workflow,
the metadata or the logs to show it. A suite tested on MySQL and deployed on
PostgreSQL silently stops terminating children.

**The two defects mask each other**, which is why one dialect could not have
found this. On MySQL the mis-cased policy "works", so the validation gap is
invisible. On PostgreSQL it falls through to ABANDON, so the collation
difference is invisible.

Note what found it: not a new test, but an existing one run somewhere else.

**Fixed at the write boundary, not in the queries.** cleat#938 refuses an
unrecognised policy when the child starts, so the value can no longer reach a
column three databases disagree about. A `COLLATE` clause on the predicates
would have fixed the comparison and left the mis-cased value in the column,
still meaning different things to different readers — including to a human
running a `SELECT`.

Rejecting rather than normalising was a deliberate call. Upper-casing would also
close the divergence and would keep working anyone relying on lower-case
matching on MySQL — which is the objection to it, not a mitigation: that
behaviour is a bug they cannot know they depend on, and making it official on
three databases makes it permanent.

The test was dialect-aware while the defect was open and is not any more. That
is the clearest statement of what the fix did: there is nothing left for the
dialects to disagree about.

**What is not wrong.** TERMINATE and REQUEST_CANCEL both work. An earlier
version of these tests reported "a TERMINATE child completed anyway", which was
this port's own thin timing margin — 500ms between the child's sleep and the
parent's — and not the engine. Direct measurement of the row across the
parent's completion showed the correct transition:

```
ready | running -                             gen=1
done  | failed  parent workflow terminated    gen=2
```

The tests now measure the ordering rather than assume it, and a child that
finishes before its parent fails as a harness problem naming itself as one.


---

## 4. A single signal delivery satisfies two `AwaitSignals`

**Class:** Bug
**Upstream sample:** `await-signals/`
**Status:** Filed — cleat-team/cleat#933

**What upstream asserts**

Each named signal is awaited and consumed once. A workflow waiting for three
distinct signals proceeds when all three have arrived, and one delivery
advances exactly one wait.

**What cleat does**

One delivery satisfies more than one await. `workflows/twoawaits/main.go` is
the reproduction and ships with this port; it contains two straight-line
`AwaitSignals` calls and nothing else.

Start it, wait for it to suspend, deliver `a` once, deliver nothing else:

```
run1: done | {"first":"a","second":"a"} | signal rows left=0
run2: done | {"first":"a","second":"a"} | signal rows left=0
run3: done | {"first":"a","second":"a"} | signal rows left=0
```

Three awaits instead of two fails differently — a checksum mismatch at step 2,
with two byte-identical `await_signals` events in history.

**Assessment**

Not the duplicate that `engine/signaller.go:312` already tolerates. That
comment's reasoning depends on a delivery row SURVIVING a failed consume, and
the row count above is zero: `ConsumeSignal` succeeded and the second delivery
came from somewhere else.

That distinction is the whole finding, and it nearly went unfiled. The comment
made a real defect look like documented behaviour — the mirror image of the
child-workflow case in #3, where a comment made a harness bug look like a real
defect. The discriminator in both is the same: test the premise the comment's
argument rests on, not its conclusion.

Four assertions in `tests/await_signals_test.go` are skipped on this, and
`TestOneDeliveryCurrentlySatisfiesTwoAwaits` pins the defect so the port
notices the fix — the construction the DBOS port used for cleat#900.

---

## 5. There is no "await these N distinct signals" primitive

**Class:** Missing API
**Upstream sample:** `await-signals/`
**Status:** Open

**What upstream asserts**

The sample's whole subject is waiting for several DISTINCT named signals and
proceeding once each has arrived, in any order.

**What cleat does**

Two calls, neither of which is that:

| call | returns when |
|---|---|
| `AwaitSignals(names, timeout)` | ONE of the names arrives |
| `AwaitSignalsWithQuorum(names, minCount, maxRejections, timeout)` | `minCount` SIGNALS have arrived |

Quorum is the closer-looking fit and the wrong one. `minCount` counts
DELIVERIES, not distinct names, so three deliveries of `approve` satisfy a
quorum of 3 over three different names. Upstream's guarantee is that each named
signal arrived, which quorum cannot express.

So the port loops over `AwaitSignals` and de-duplicates by name itself.

**Assessment**

Arguably fine — the loop is six lines and does exactly what is needed. It is
recorded because the natural reading of the API leads to the wrong call, and
the difference is invisible in any test that sends three different names once
each, which is what a test written from the sample would do.

`TestRepeatingOneSignalDoesNotSatisfyTheOthers` is the assertion that separates
them. It is currently skipped on #4.

---

## 6. A query on an unknown run answers 200, not 404

**Class:** Bug
**Upstream sample:** `query/`
**Status:** Fixed — cleat-team/cleat#935, merged 2026-09-08

**What upstream asserts**

Nothing directly. This came from writing the sample's assertions and assuming a
settled question was settled.

**What cleat does**

```
GET /api/workflows/00000000-0000-0000-0000-000000000000/query?key=counter
200 {"key":"counter","value":""}
```

`/query` was the last run-scoped read still answering 200, and it was not among
the three cleat#900 named. The full set spans **two prefixes**, which is why an
enumeration from one route switch misses some of it:

| endpoint | status |
|---|---|
| `/api/instances/{id}/events` | #917 |
| `/api/instances/{id}/state` | already 404'd |
| `/api/workflows/{id}` | already 404'd |
| `/api/workflows/{id}/terminal` | #896 |
| `/api/workflows/{id}/history` | #917 |
| `/api/workflows/{id}/promises` | #917 |
| `/api/workflows/{id}/dag` | already 404'd |
| `/api/workflows/{id}/query` | cleat#935 |

`/routing` and `/tags` are **not** in the set: they take a definition *name*
rather than a run id, so the existence check does not apply and an empty result
for an unknown name is the normal state.

**Assessment**

Worse here than on the collection endpoints, because the empty value is *also a
legitimate answer*. A run that does not exist, a key not yet published, and a
key published as `""` are three situations with one response. The 404 separates
the first two.

The general lesson is not about this endpoint. **#900's fix closed the three
endpoints the issue listed rather than the class it described**, and the class
was stated plainly in the issue. A port written from a different engine's
assumptions asks the question again in a place the original never looked,
which is most of what a second upstream buys.

---

## 7. Query state is published, not computed

**Class:** Design difference
**Upstream sample:** `query/`, `query-workflow/`
**Status:** Won't fix — recorded

**What upstream asserts**

A query invokes a REGISTERED HANDLER when it arrives, and the handler computes
its answer from live workflow state at that moment. A caller can ask a question
the workflow author anticipated the *shape* of but not the *timing* of.

**What cleat does**

`SetQueryState(key, value)` PUBLISHES a value; a reader gets whatever was
published last. Push, not pull.

`TestAPublishedValueGoesStaleWhenTheStateMovesOn` pins it: `firstSeen` is
published once and never republished while the state it describes keeps
moving, and the reader keeps getting the original value. A Temporal handler
asked the same question would return the current one.

**Assessment**

Deliberate, and the difference is defensible — the alternative is invoking
guest code on demand from an HTTP handler, which is a much larger thing than a
query API and brings its own failure modes (what happens when the handler
suspends, or the worker holding the run is gone).

It is recorded because *nothing in the API's shape tells a caller which model
they are in*, and a reader arriving from Temporal will assume pull. Two
consequences follow that are easy to meet by surprise: a value can be stale
without being wrong, and an unpublished key is indistinguishable from an
unanswerable one — there is no handler-not-registered error, because there is
no handler.

`TestAQueryStillAnswersAfterTheRunHasFinished` establishes the useful half of
the push model: query state OUTLIVES the run, so it can be used to inspect a
workflow that finished. That is a genuine advantage of publishing over
computing, and it is worth having a test on.

---

## 8. The same path segment means two different kinds of identifier

**Class:** Design difference; the silent half is fixed
**Upstream sample:** none — found reading the route table while porting
**Status:** Fixed — cleat-team/cleat#942, closed by #945 on 2026-09-08

**What upstream asserts**

In Temporal a workflow ID and a workflow TYPE are different things in different
places: the type is registered on a worker, the ID addresses a run, and no API
path takes either interchangeably.

**What cleat does**

Both live in the same path segment, disambiguated only by the suffix —
`{id}/history` and `{id}/query` take a run id, `{name}/routing`,
`{name}/tags` and `{name}/start` take a definition name. The namespaces never
overlap, so a run id in the name position was answered `200 []`, byte-identical
to a real definition with no rules.

**Fixed.** The name-scoped reads now 404 for a name that is not a definition:

```
GET /api/workflows/no_such_name/routing                    404
GET /api/workflows/00000000-0000-0000-0000-000000000000/routing  404
GET /api/workflows/saga_transfer/routing                   200 []      <- control
```

The path shape is unchanged — a caller still cannot tell from the URL which kind
a segment wants — but giving the wrong kind is now an error rather than a
plausible empty answer.

**One path deliberately left**

```
DELETE /api/workflows/no_such_workflow_name/tags/stable -> 200
```

*For leaving it:* DELETE is conventionally idempotent, and removing a tag that
is not there is a no-op success.

*Against:* the thing that does not exist is the DEFINITION, not the tag. "The
tag was removed" and "there is no such workflow" share one response, so a caller
who typos the workflow name is told the deletion succeeded. #945 has just
decided an unknown definition is a 404 on the reads, and the writes already 409;
this is the last path where an unknown definition is silently fine.

Not filed as a defect — idempotency is a real principle and this is a decision
about which convention wins. Pinned in
`TestDeletingATagOnAnUnknownDefinitionCurrentlyAnswers200` so the decision is
visible and the port notices whichever way it goes.

**Assessment**

`TestAKnownDefinitionWithNothingIsStill200` is the control and the one that
mattered: an over-broad fix — 404 whenever the collection comes back empty —
passes every unknown-name assertion and breaks every caller polling a definition
that simply has no routing yet, which is most of them.

## 9. The durable clock goes backwards on the first durable event

**Class:** Bug
**Upstream sample:** `timer/`, `sleepfor/`
**Status:** Filed — cleat-team/cleat#944

**What upstream asserts**

That a timer is an ENGINE primitive rather than a library call: deterministic on
replay, and not a reading of the wall clock.

**What cleat does**

Two of the Timer contract's four claims hold exactly. Eight consecutive runs
sampling `NowMs()` at four points:

```
t0->t1 (cpu work)   t1->t2 (durable call)   t2->t3 (sleep 200ms)
      +0                    +355                    +200
      +0                     -5                     +200
      +0                    -26                     +200
      +0                    -25                     +200
      +0                    -18                     +200
      +0                     +9                     +200
      +0                    -23                     +200
      +0                    -15                     +200
```

Virtual time does not advance during CPU work — `+0` every run. A sleep advances
the clock by exactly the sleep — `+200` every run, never wall-clock elapsed.
Those are the hard claims and they are solid.

The third reading is non-monotonic, negative in six runs of eight.

**Assessment**

Two clock domains feed one value. `Now()` before any event is the workflow row's
`created_at` — the **database** clock (`engine/engine.go:74`). The first recorded
event's timestamp is the worker's `time.Now()` (`engine/lifecycle.go:148`).
Nothing reconciles them, so the step between them is the offset between two
machines' clocks, in whichever direction they differ.

A workflow computing `Now().Sub(start)` across its first durable call gets a
negative duration. The usual response to a negative duration is to clamp it,
which hides it.

It also undercuts what the other two claims buy. The contract's value is that
virtual time is *derived* rather than observed — that is what makes replay
reproducible. A value that mixes in a second observer's clock is only derived
until the two observers disagree, and they always eventually do. 26ms is small
because both clocks are on one laptop; a worker and a database in different
zones have no such bound.

Pinned rather than skipped: the assertion is one line, and skipping it would
leave the two claims that DO hold without the monotonicity check that gives them
context.

---

## 10. The determinism checks skip any function that makes no host call

**Class:** Bug (scope, not rules)
**Upstream sample:** `goroutine/`, `mutex/`
**Status:** Filed — cleat-team/cleat#949

**What upstream asserts**

`goroutine/` runs work concurrently INSIDE one workflow using `workflow.Go`,
which Temporal schedules cooperatively and deterministically. The pattern is
safe there.

**What cleat does**

Forbids the whole family — goroutines (E001), channels (E002), sync primitives
(E013) — on the grounds that workflow code is single-threaded by design. So the
sample cannot be ported, and the port is written as its own refusal.

Which found that the refusal is conditional on something unrelated to
determinism. Three builds of the same `sync.Mutex`:

| fixture | closure | result |
|---|---|---|
| `syncmutex` — no host call | `0 in cleat closure` | **builds**, no diagnostic |
| `mutexwithcall` — one `h.SetQueryState` added | `1 in cleat closure` | two E013s, refused |

The two files differ by one line.

**The case that matters is a helper.** `helperescape` has an entry point that
calls the host — so it is checked, and it suspends and replays — calling a
helper that does not. The helper carries six violations across three codes:
goroutines, channel send, receive and `close()`, `sync.Mutex` and
`sync.WaitGroup`. The build reports none of them, and the analyzer's own line
reads `2 functions, 1 in cleat closure`: it counted the helper without checking
it.

**Assessment**

The rules are right; the *set they are applied to* is wrong. "Only analyse what
can reach a host call" is correct for closure analysis, where the question is
which host functions to import and a function reaching none contributes
nothing. The determinism checks were attached to the same traversal and are
asking a different question — determinism is a property of everything the
workflow executes, not everything that calls out.

Replay re-runs the workflow function and constrains only the results of host
calls, not local computation, so an unchecked helper is re-executed every time.

`TestTheRuleIsRealWhenItApplies` is the control and everything else here is
meaningless without it: if the analyzer simply did not implement these codes,
every "it built" observation would be equally explained.

---

## 11. A workflow times out on a signal that is already in its queue

**Class:** Bug
**Upstream sample:** `signal-counter/`
**Status:** Filed — cleat-team/cleat#953

**What upstream asserts**

Send N signals, the count is N. The sample accumulates a running total from
repeated deliveries of one name and completes on a terminal signal, so its
guarantee is arithmetic.

**What cleat does**

Under rapid delivery it under-counts, and the missing signals are still in the
table:

```
six deliveries, all 200:  tick x5 then done
final: status=done  {"count":3,"seen":"tick,tick,tick","timedOut":true}
       pending_signals=3
```

The `done` it was waiting for sat in `workflow_signals` for the whole remaining
budget. The rows are still there after the run ends.

**Nothing is lost.** Counted at one instant mid-run: `count=2` consumed,
`tick x3, done x1` remaining, `status=ready` — every one of the five ticks
accounted for. The first reading was "two were dropped", and the discriminator
was one query rather than an argument.

**Assessment**

The variable is whether a signal arrives while the workflow is **suspended** or
while it is **awake handling a previous one**.
`TestTheCountIsVisibleWhileTheWorkflowRuns` sends one at a time and waits for
the count to advance between each; it is green. The exposed window is exactly
the time the workflow spends processing.

`AwaitSignals(names, timeout)` returning `timedOut` is supposed to mean "none
of these arrived in time". Here it means "none arrived while I happened to be
suspended" — not a property any caller can reason about, since it depends on
the workflow's own processing time against the sender's spacing.

Distinct from #933 symptom A. That is an over-count from one delivery
satisfying two awaits; this is an under-count with the deliveries still queued.

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
