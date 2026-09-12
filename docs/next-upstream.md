# Scoping a second upstream

**Decision (2026-09-09):** finish the 33 portable cases still outstanding in
`dbos-transact-py`, then stop mining it and add a second upstream project.

**Recommendation:** `microsoft/durabletask-go`, Apache-2.0.

This document records why the first upstream is finished, how the candidates
were compared, and what the second one is expected to yield. It is a proposal,
not a port: nothing here has been ported and the yield figures below are
predictions with a stated basis, not measurements.

---

## Why `dbos-transact-py` is finished

All eight files in scope have now been surveyed case by case, by four sessions
working independently. The surveys agree on a shape that the coverage table
does not show:

| upstream file | cases | portable, unported |
|---|---:|---:|
| `test_dbos.py` | 61 | 17 → 9 → **2**, see below |
| `test_failures.py` | 37 | 5 → **0** |
| `test_scheduler.py` | 35 | 5 → **0** |
| `test_client.py` | 57 | 3 → **0** |
| `test_async.py` | 33 | 1 → **0** |
| `test_concurrency.py` | 11 | 1 → **0** |
| `test_workflow_management.py` | 46 | 1 → **0** |
| `test_queue.py` | 91 | 0 |
| **total** | **371** | **33 → 25 → 18 → 2** |

*The right-hand column is now checked rather than typed:
`scripts/check-worklist-totals.py` reconciles every row against the worklist it
summarises and against the ported tests, and CI fails when a row contradicts its
own evidence. The arrows are kept because this document's subject is how the
number moved.*

> **Third correction (2026-09-10): the 18 does not reconcile with the worklists
> it summarises, and the direction of the error is downward.** Two rows are
> contradicted in bold by their own worklist headings — `test-client.md` says
> *"### Portable — 3 · **ported 2026-09-09**"* and `test-scheduler.md` says
> *"### Portable — 5 · **all five ported 2026-09-09**"*, against 3 and 5
> **unported** here. That is 8 of the 18.
>
> Checking the rest mechanically — does a ported test name the upstream case in
> its docstring, the convention this port already follows — **13 of the 14
> portable cases enumerated by name across the worklists are cited by a test
> that exists.** The fourteenth is `test_step_retries_no_final_sleep_async`,
> which `test-failures.md` itself says to merge into its sync twin.
>
> `test_failures.py`'s row says 5; four are cited (one,
> `test_a_permanent_failure_is_not_reported_as_an_exhausted_budget`, names
> `test_step_should_retry_on_last_attempt` in its own docstring) and the fifth is
> that merge. `test_async.py`'s single case is cited too.
>
> **A defensible remaining figure is 2–4, not 18** — plausibly `test_dbos.py`'s 2,
> `test_concurrency.py`'s 1, and `test_workflow_management.py`'s 1, which that
> worklist says is an ISSUES entry rather than a test to write.
>
> **What is measured and what is not.** Measured: the worklist headings, and that
> 13 of 14 named cases appear in a ported test. Not measured: that each of those
> tests actually asserts the upstream property — citation is a strong signal and
> not a proof, and I did not re-read all thirteen.
>
> **This is the failure this document diagnoses, applied to its own headline.**
> The text below says an unenumerated count has nothing to reconcile against.
> The 18 is a column of per-file totals, and the two files whose worklists state
> their status in bold are the two it contradicts. The enumerated sections were
> right and the summary was stale, which is the direction summaries fail in.
>
> **It changes the decision.** *"Finish the 18, then add a second upstream"*
> reads very differently at 2–4: the first upstream is close to finished, and the
> second is due now rather than after a block of work. Someone should confirm the
> residual by reading those two-to-four cases before the count is quoted again —
> including this correction.


**Second correction, and the two are not the same mistake.** cleat-agent1-31
audited their own 9 against cleat's surface case by case and it is **2**, which
makes the total **18**. Four of the nine need something cleat does not have — an
arbitrary-workflow status read from inside a workflow (poll/await_child are
children-only), a `parent_workflow_id` field on `WorkflowInstance` (the column
is written on every child row and surfaced to nobody), an idempotency key on
`cleat_signal_workflow`, and `list_workflows` filters that do not exist. Three
more are already covered here under different local names.

**The 9 was enumerated AND machine-verified, and still wrong, which is the part
worth keeping.** The check that ran proved *these 61 names are the file's cases,
partitioned, none invented* — a claim about the **upstream**. "Portable" is a
claim about **cleat**, and it was screened by scanning the host-call export
list, which answers *does cleat have something in this area* rather than *can a
port assert this end to end*. A verified enumeration made an unverified
classification look verified; they shipped in one sentence and only one had been
checked.

So the three clauses below are necessary and not sufficient. A fourth belongs
with them: **name which proposition each check establishes.** Enumeration
against the pin and portability against cleat are different claims needing
different evidence, and satisfying the first says nothing about the second.

**First correction, hours after this document was published.** The `test_dbos.py`
figure of 17 does not reproduce. cleat-agent1-31 re-derived it by enumerating
the cases *by name* and got **9**, which makes the total **25**, not 33. Six of
the eight lost have a subject the original survey did not screen for
(`wait_first`, and `DBOS.step_status`/`step_id` introspection), and a further
**10 cases are not engine assertions at all** where that section recorded none
— assertions that a Postgres trigger named `dbos_notifications_trigger` exists,
that `recv` survives LISTEN/NOTIFY falling back to polling, that
`len(dbos._timeout_tasks) == 0`.

**The structural reason the 17 survived is worth more than the number.** It was
never enumerated. The `test_dbos.py` section states its four bucket totals and
then documents only the 42 blocked and the 2 deliberate, so nothing in the tree
listed which cases made up the 17 — and **an unenumerated count has nothing to
reconcile against.** Every other survey here was caught or confirmed by
reconciling two independent derivations; that one offered no second view of
itself, and three separate defects in it surfaced the same day (this count, an
`ISSUES` entry it claimed to have filed and had not, and the missing
enumeration itself).

The rule that follows has three clauses, and the first one alone is not the
fix. cleat-agent1-31's `test_workflow_management.py` survey **was** enumerated
by name and still mis-bucketed two cases — its classifier tested fork before
GC and took the first match, and the name list stayed internally consistent
throughout. What caught it was ISSUES 23's independently-derived 18 against
that survey's 16.

1. **State the buckets by name.** Otherwise there is nothing for a second
   reader to disagree with, which is how the 17 survived.
2. **Reconcile the list against a total derived a different way.** An
   enumeration makes reconciliation possible; it does not perform it. This is
   the clause that does the catching.
3. **State the denominator and how it was derived.** `^\s*def test_` gives 138
   cases for `test_dbos.py` where `^def test_` gives 61; the 77 difference are
   `@DBOS.workflow()` fixtures declared inside test bodies. A wrong denominator
   is wrong in every bucket at once.

`test_dbos.py` is the largest single contributor to the remaining work, so this
correction moves the headline. It does not move the conclusion — 25 is the same
answer as 33 to the question "is this upstream close to mined out", and it is
the direction that makes the case for a second upstream stronger rather than
weaker.

**Four of those eight figures are not on `develop` yet.** `test_client.py` (3)
is ports#111, `test_async.py` (1) is ports#110, `test_workflow_management.py`
(1) is ports#107, and `test_queue.py` (0) with `test_concurrency.py` (1) are
ports#108 — all open at the time of writing. The other three come from
`WORKLIST.md` as merged. If you are reading this after those land the table is
checkable; if you are reading it before, four rows cite work you cannot see,
and that is the reason to say so rather than let the total read as settled.

The right-hand column is also **not** `cases − cases here`. The README used to
carry a `Cases here` column counting this port's tests mapped to an upstream
file, while the surveys count upstream cases read one at a time. The two
disagree — ws3 found `test_client.py` has 13 cases covered where that column
credited 8 — so combining them into a percentage would have produced a number
with no meaning.

**ports#134 removed the column**, so the arithmetic is no longer available to
do by accident. The warning stays because the two kinds of count still exist
and are still easy to mix: 33 is a sum of like with like — cases a survey read,
judged portable, and found unported.

**The `cases` column is a nominal denominator and always was.** What each
survey found is a *ceiling*, not a backlog:

- `test_queue.py` — 72 of 91 need queue controls cleat has no counterpart for.
- `test_client.py` — 30 of 35 declines are **one architectural fact**: DBOS's
  client is a library holding a database connection, cleat's is HTTP.
- `test_async.py` — a third of the file asserts properties of the Python SDK's
  own async machinery, which would still be valid if DBOS's storage layer were
  replaced entirely.
- `test_concurrency.py` — 9 of 11 drive `asyncio.gather` inside one workflow,
  which cleat's determinism analyzer refuses at build time.

None of that is a gap in cleat. It is the boundary of what one upstream, built
on one set of architectural assumptions, can say about a different engine. A
second upstream is worth more than the tail of this one because it brings
different assumptions, not more cases.

---

## Candidates, and the licence filter first

Both repositories are Apache-2.0 and public, and `docs/licensing.md` governs.
Verified by API rather than by reputation, because the last time this was
assumed it was wrong.

**Last re-verified: 2026-09-10.** All ten rows unchanged. The date is here
because "verified by API" is a claim that decays: a licence can change, and a
table that says how it was checked but not when cannot tell a reader whether it
still holds. Re-derive in one pass:

    for r in <the repos below>; do
      printf '%-34s %s\n' "$r" "$(gh api "repos/$r/license" --jq '.license.spdx_id' 2>/dev/null || echo '404 — no licence')"
    done

Note the `|| echo` — `gh api` exits non-zero on the 404 that matters most, and
without it the row for an unlicensed repository prints blank and reads like a
lookup that simply returned nothing.

| candidate | SPDX | verdict |
|---|---|---|
| `microsoft/durabletask-go` | Apache-2.0 | **eligible** |
| `temporalio/sdk-go` | MIT | eligible |
| `temporalio/sdk-python` | MIT | eligible |
| `uber/cadence` | Apache-2.0 | eligible |
| `conductor-oss/conductor` | Apache-2.0 | eligible |
| `restatedev/sdk-typescript` | MIT | eligible |
| `temporalio/features` | **404 — no licence** | excluded, again |
| `golemcloud/golem` | NOASSERTION | excluded unread |
| `restatedev/restate` | NOASSERTION | excluded unread |
| `inngest/inngest` | NOASSERTION | excluded unread |

`temporalio/features` remains the most attractive suite and remains
unusable — `GET /repos/temporalio/features/license` still returns 404.
`docs/licensing.md` already covers it: describe from prose, never copy.

`NOASSERTION` means GitHub could not match a recognised licence. That is not
proof of a bad licence, but reading a source-available licence carefully enough
to rely on it is work with no payoff while three permissive candidates remain.

## The second filter, for whoever picks a third

The licence table above is the first gate. This is the second, and it is the one
that decided `durabletask-go`: **§1 below asks whether a suite's tests run
without external infrastructure.** That is not about running them — this repo
re-expresses assertions and never executes upstream — it is a proxy for whether
the assertions are *about an engine* or about standing one up.

Measured 2026-09-10 from each candidate's own CI, so it is checkable rather than
recalled:

| candidate | how its CI runs tests | reads as |
|---|---|---|
| `temporalio/sdk-go` | `integration-test -dev-server`, plus a `docker-compose-test` job | needs a **server**; the interesting assertions are in the integration suite |
| `temporalio/sdk-python` | `poe test --workflow-environment time-skipping` | needs a **downloaded test server**, but no `services:` block — a middle case |
| `uber/cadence` | `ci-checks.yml` and friends; not examined | unexamined |
| `conductor-oss/conductor` | `ci.yml`; not examined | unexamined |
| `restatedev/sdk-typescript` | **no `ci.yml`** — its workflows are `_test-<runtime>-template.yml` per runtime | unexamined; the shape suggests runtime-matrix testing rather than engine assertions |

**`restatedev/sdk-typescript`'s row is the one to be careful with.** A first pass
recorded "no server needed" for it, from a grep over a `ci.yml` that does not
exist — 0 bytes fetched. An empty search over an absent file is not evidence,
and it is the same mistake this repo keeps documenting. Its per-runtime
templates need reading before anything is claimed.

**What this does not settle.** Needing a server is not disqualifying on its own:
we read assertions, we do not run them. It matters because a suite whose setup
is a server tends to assert against that server's semantics, while
`durabletask-go`'s backend-contract tests assert against a *storage* contract,
which is cleat's shape (§2). A candidate that needs a server may still be worth
porting if its assertions survive the translation — that judgement needs the
same case-by-case read the two existing surveys did, and nobody has done it.

Cost, unchanged and worth restating before anyone starts: on the evidence of the
first two ports, **the survey is a day and the fixtures are the long pole.**

---

---

## Why `durabletask-go`

### 1. Its tests run without external infrastructure

The decisive practical difference. `tests/orchestrations_test.go` builds a task
hub over an **embedded SQLite backend** and runs — no server, no broker, no
container:

```go
client, worker := initTaskHubWorker(ctx, r)
id, err := client.ScheduleNewOrchestration(ctx, "EmptyOrchestrator")
metadata, err := client.WaitForOrchestrationCompletion(ctx, id)
```

Cadence and Conductor are server products whose suites need the full stack.
Temporal's SDK integration tests need a dev server. For a harness that already
juggles three databases and a worker, an upstream that needs nothing extra to
*read and understand* is worth a great deal.

### 2. It is a backend contract, which is cleat's shape

`durabletask-go` separates orchestration semantics from storage behind a
`backend` interface with SQLite and MSSQL implementations. `tests/backend_test.go`
(10 cases) and `tests/runtimestate_test.go` (10 cases) test **that contract
directly**, which is the same layer as cleat's `engine`/store split and the
same multi-dialect concern the nightly matrix exists for.

No file in `dbos-transact-py` tests a storage contract; DBOS's tests go through
the SDK.

### 3. It probes cleat exactly where open questions already are

Not a general argument — three specific cases, read at
`3fe35d93fe1d2bdab21a3d85c14867532adef0b0`:

**`Test_TerminateOrchestration_Recursive`** builds Root → L1 → L2, terminates
the root **parametrised over `recurse` true and false**, and asserts
`assert.NotEqual(t, recurse, executedActivity)` — descendants must run their
activity when recursion is off and must not when it is on.

**Correction: the sentence that stood here was scope-wrong, and it inverts the
conclusion.** It said cleat's cancellation is `WHERE id = $1` with no
`parent_workflow_id` traversal, citing ISSUES 29. That is true of **cancel**.
These cases exercise **terminate**, and cleat's terminate has a configurable
cascade already: `parent_close_policy` with three legal values —
`ABANDON` (default), `TERMINATE`, `REQUEST_CANCEL` — validated by
`ValidateParentClosePolicy` (`engine/parent_close_policy.go`), enforced by
`enforceParentClosePolicy` with a per-arm `UPDATE ... WHERE parent_workflow_id
= ?` on all three dialects, called from every terminal path.

So `WithRecursiveTerminate(true|false)` is expressible today. The decision sits
at **child spawn** rather than at the **terminate call**, and both branches of
upstream's parametrised assertion have a counterpart.

That moves these four cases from *"probes a choice cleat has not made"* to
**"cleat made this choice, at a different layer, and nothing has ever tested
it"** — which is a stronger argument for the port, not a weaker one. Found by
cleat-ws3 while surveying the file; verified here independently before this
correction was written.

One question is deliberately left unfiled. Upstream builds **three** levels,
and cleat's cascade is one level of SQL: a `TERMINATE` child is set to
`status='failed'` directly by that UPDATE, bypassing `FailWorkflow` — which is
what calls `enforceParentClosePolicy` for the next level down. Read that way a
grandchild is reached only when the intermediate child owed a defer phase. That
is three correct citations and a chain with no branch in it, which is the exact
shape of a prediction retracted eight hours earlier in ports#129. **A
three-level `TERMINATE` fixture settles it in one run**, and until one exists
this is a question rather than a finding.

**`Test_SingleActivity_ReuseInstanceID{Ignore,Terminate,Error}`** makes
instance-id reuse a **configurable policy** — ignore the second, terminate the
first, or error. cleat has exactly one behaviour, and this port pinned it today
(`test_a_completed_run_still_answers_for_its_idempotency_key`): the
`idempotency_keys` binding outlives the run by seven days. Three policies
against one behaviour is a far sharper lens than DBOS's single alternative was.
`ReuseInstanceIDIgnore` also asserts the surviving run's `CreatedAt` is the
*first* one's, which is a timestamp assertion cleat can make.

**`Test_SuspendResumeOrchestration`** suspends a running orchestration, raises
events that must **buffer without being consumed**, asserts it does not
complete and reports `SUSPENDED`, then resumes and asserts it consumes the
buffered events. cleat suspends workflows on awaits but has no operator-initiated
suspend, and `cancel` is terminal by design with `resume` rejected deliberately.
This is a direct probe of a decision cleat has already made, which is the most
useful kind of case: it either confirms the decision or names its cost.

### 4. It is a different model from DBOS

DBOS decorates Python functions and enqueues them onto named queues.
durabletask-go registers orchestrators and activities and drives them through a
replay loop with explicit external events, timers and sub-orchestrations. cleat
is closer to the second, which means fewer cases will decline on "cleat has no
such concept" — the failure mode that consumed most of `dbos-transact-py`.

---

## Predicted yield, and how to check it

**This is a prediction, not a survey.** The `dbos-transact-py` surveys exist
because a prediction of this kind was wrong four times. **The count below is
also wrong: it says 26, and the collected total is 30.** Four functions are
`for _, x := range []bool{true, false}` loops with a `t.Run` inside, so each
contributes two cases — `Test_ExternalEventTimeout` over `raiseEvent`, and the
three `_Recursive` tests over `recurse`. 22 plain + 4×2 = 30, which makes 50
in scope across the three files rather than 46.

That is the definitions-versus-collected-cases distinction this repo's own
README documents, made one document after quoting it. Two derivations agreed at
26 and neither helped, because both counted functions. The 26 cases in
`tests/orchestrations_test.go`, classified by whether cleat has the surface at
all:

| | cases | basis |
|---|---:|---|
| cleat has the surface | ~17 | timers, activities, chains, retries, fan-out, sub-orchestrations, continue-as-new, external events, terminate |
| probes a cleat decision | ~5 | recursive terminate ×2, reuse-id ×3 |
| likely declines | ~4 | concurrent timers and `IsReplaying` (determinism analyzer), recursive purge, suspend/resume |

Plus 20 backend-contract cases whose portability is genuinely unknown until
someone reads them against `engine`.

**SUPERSEDED for `orchestrations_test.go` by
`durabletask-go-orchestrations-survey.md`, which read the cases** — and the
first thing that survey corrected was the denominator here: 26 is the
*function* count, four functions are `range []bool{true,false}` loops, and the
file collects **30**. The prediction below is kept because it was wrong in an
instructive way, not because it is usable.

**Do not trust this table.** It was produced by reading 26 test *names* and one
body each for four of them, which is precisely the method that reported
`test_client.py` as 8 covered when it was 13, and `test_async.py` as "mostly
async mirrors" when the mirror bucket was a third of the claimed size. The
first task in the port is the survey, by the method in `WORKLIST.md`:

1. `grep` the new port's `ISSUES.md` before reading upstream.
2. Name-level census — a **lower bound on coverage, never an upper one**.
3. Reconcile against an independent count; a partition that sums correctly is
   not a partition that is right.
4. Separate "cleat lacks the mechanism" from "not an engine assertion at all".

---

## What this does not get us

- **Not a Go-language port.** The port re-expresses assertions against cleat's
  own SDK; upstream's language decides only how the assertions are read.
- **Not more dialect coverage.** The nightly matrix already runs every port on
  all three. A second upstream adds cases, not backends.
- **Not a replacement for `dbos-transact-py`.** Its 33 outstanding cases stay
  outstanding, and its ISSUES ledger stays the record for everything found
  through it.
- **Not free.** `docs/adding-a-port.md` sets out what a new port costs:
  a directory, a harness entry, a fixture set of workflows, and a place in the
  nightly matrix. On the evidence of the first port, the survey is a day and
  the fixtures are the long pole.


---

## The port has a reach limit, and it is now measured (2026-09-10)

This document recommends a backend contract over a client library on the
grounds that it is *closer to cleat's shape*. Having judged
`backend_test.go`'s ten cases against cleat
(`durabletask-go-backend-survey.md`), that is true and **incomplete**: closer in
subject, and further out of reach.

**Four of the ten are satisfied by cleat and cannot be asserted from here.** Not
"cleat lacks them" and not "upstream-internal" — a fifth verdict, with two
distinct causes:

| cause | cases |
|---|---|
| the surface is a **store method with no HTTP route** — `ClaimWorkflow` returning `(nil, nil)` on an empty queue is cleat's `ErrNoWorkItems`, and no route exposes it | `Test_ScheduleActivityTasks`, `Test_ScheduleTimerTasks` |
| the property is a **timing distinction smaller than the poll interval**, and the mechanism differs by dialect | `Test_AbandonOrchestrationWorkItem`, `Test_AbandonActivityWorkItem` |

The second is the sharper one. `ReleaseWorkflow` makes abandoned work
immediately re-claimable and `pgNotify`s so a waiting worker wakes — but
`-poll` defaults to **500ms**, which bounds how much a notify can save, and
`pgNotify` is **PostgreSQL-only**: MySQL and SQL Server disable it by
construction. A test timing the difference would measure a different mechanism
on each dialect while appearing to measure one property.

### What this means for choosing the next upstream

**The port's reach is the HTTP surface, and an upstream's yield here is bounded
by how much of its subject that surface exposes** — not by how close its subject
is to cleat's. Those pull in opposite directions:

- a **client library** tests things a client can see, so what is portable is
  portable — but most of it is SDK shape rather than engine behaviour
  (`test_client.py`: 3 of 57);
- a **backend contract** tests engine behaviour, which is what we want — and a
  growing fraction of it is reachable only from inside the process
  (`backend_test.go`: 4 of 10 satisfied-but-unobservable, against 2 already
  covered and 3 genuinely not portable).

So the criterion is not *engine-ness*. It is **the intersection of engine-ness
and HTTP-observability**, and `backend_test.go` is the first corpus where that
intersection has been measured rather than assumed.

**The practical consequence** is that engine-level assertions cleat *satisfies*
and this suite *cannot see* belong in cleat's own Go tests, not in a port — and
saying so is more useful than recording them as unportable, because they are
neither absent nor covered. Anything routed that way should carry the property
and the reason the port cannot hold it, or it will be re-derived by the next
survey that reads the same file.


---

## The third filter, and it reverses how to read the second (2026-09-10)

Written after finishing `uber/cadence` (132 cases → 10 issues) and judging
`durabletask-go`'s `backend_test.go` case by case. Both gates above are sound
and there is a third, which only became visible once a corpus was judged all the
way through to *"can this suite assert it?"*.

**The port's reach is the HTTP surface.** An upstream's yield here is bounded by
how much of its subject that surface exposes — not by how close its subject is
to cleat's. Measured:

| corpus | engine assertions | reachable from an HTTP port |
|---|---|---|
| `test_client.py` (a client library) | 3 of 57 | all of them |
| `backend_test.go` (a backend contract) | 7–8 of 10 | **4 of 10 are not** |

Four of ten are satisfied by cleat and unassertable from here — two because the
surface is a store method with no route (`ClaimWorkflow` returning `(nil, nil)`
*is* upstream's `ErrNoWorkItems`), two because the property is a timing
distinction smaller than the 500 ms poll interval whose mechanism, `pgNotify`,
is PostgreSQL-only.

**So the criterion is the intersection — engine-ness AND HTTP-observability —
and the two pull against each other.**

### What that does to the second filter

§"The second filter" reads *"tests run without external infrastructure"* as a
proxy for **assertions about an engine rather than about standing one up**. That
proxy is sound and its sign is the opposite of what it looks like.

`backend_test.go` needs no server precisely because it tests the backend
**interface**, in process, below any API. That is what made 4 of its 10 cases
unreachable. Conversely, a suite that **requires a server** is asserting through
that server's API — which is the surface a port can drive.

**A suite needing external infrastructure is evidence FOR portability here, not
against it.** The table in that section should be read with its verdict column
inverted:

| candidate | its CI | second filter reads | **third filter reads** |
|---|---|---|---|
| `temporalio/sdk-go` | `integration-test -dev-server` | needs a server | **assertions go through the API** |
| `temporalio/sdk-python` | `--workflow-environment time-skipping` | middle case | assertions go through the API |
| `conductor-oss/conductor` | unexamined | unexamined | a server with a REST API |

### Recommendation, and its uncertainty

**`temporalio/sdk-go`'s integration suite**, on three grounds:

1. **It drives a running server over a client API** — engine behaviour, observed
   the way a port observes it.
2. **Subject overlap is established, not assumed.** Temporal is Cadence's
   descendant and this repo has just read 132 Cadence cases, so the areas that
   produced residue — lifecycle, listing and filtering, cancellation semantics —
   are known to map onto surfaces cleat exposes, and the areas that produced
   none (shard range ids, history branch trees, cross-cluster version histories)
   are known not to.
3. MIT, and eligible in the table above.

**What is not established:** I have not read the suite. The yield figure is
unknown and should stay unknown until someone reads a sample — this document's
own history is what happens when a count is published before it is enumerated.
The right first step is one file, read case by case, with the four verdicts this
repo now uses — *gap*, *already covered*, *not portable*, and **satisfied but
unobservable from here** — and a fifth from the Cadence work when it applies:
*present and broken*, which is the one no name-level triage can reach.

### The first step has been taken, for one cluster (2026-09-11)

[`temporalio-sdk-go-schedules-survey.md`](temporalio-sdk-go-schedules-survey.md)
reads the 20 `TestSchedule*` cases of `test/integration_test.go` at
`902937accd7ac67cd8ed16e73b1db2b75cab48a7`. **That is 20 of the file's 256
methods, and the file is one of twenty-four in `test/` — it is not a verdict on
the upstream.**

Yield from those 20: one defect filed (cleat#1297, three schedule verbs
reporting success for a name that does not exist) and two novel portable
assertions. Notably **zero** in the *satisfied but unobservable* bucket that
`backend_test.go` filled 4 of 10 with — schedules are administered over HTTP by
design, so the port's reach is the whole surface. That is evidence for the third
filter above, from the first corpus picked using it.

A caution from the Cadence corpus that transfers directly: **the residue
concentrated in two files of fourteen**, and file names did not predict which.
`dbVisibilityPersistenceTest.go` was dismissed from its name by two sessions
independently and was the second most productive file in the corpus. Triage by
the API surface a case *body* exercises, and expect the internals files to yield
nothing however carefully they are read.

### A second cluster, and a cheaper way to choose the next one (2026-09-12)

[`temporalio-sdk-go-updates-survey.md`](temporalio-sdk-go-updates-survey.md)
reads the 27 `UpdateWorkflow` cases of the same file — **37 collected cases**
once the twelve subtests inside two of them are counted.

Yield: **7 gaps — all now ported**, **1 present-and-broken** (cleat#1330, an
update name is single-use per workflow and the three dialects disagree about the
second request), 5 design differences, 1 capability gap, 1
satisfied-but-unobservable, 12 not portable. Plus one defect the cases did not ask about and the *probe*
found: cleat#1331, a sub-millisecond `AwaitSignals` timeout livelocks the
workflow forever.

**The cluster was chosen by bucketing all 256 methods by the client call their
BODIES make**, which took one pass and is the operational form of this
document's own caution that file names do not predict yield. Updates were the
largest cleat surface with zero coverage in any port; the same table shows what
is left.

Two things that generalise:

**The *satisfied but unobservable* bucket stayed near zero again** — 0 of 20 for
schedules, 1 of 27 for updates, against 4 of 10 for `backend_test.go`. That is
the third filter's prediction holding twice, from two different clusters: a
suite that drives a server is one a port can drive.

**The probe found more than the cases did.** Every update behaviour the cases
ask about turned out correct; cleat#1331 is in the scaffolding those cases
needed, and no amount of reading `engine/updater.go` would have produced it.
Which is the argument for porting over surveying, stated as a measurement
rather than as a preference.

## The whole of `temporalio/sdk-go`'s `test/`, bucketed (2026-09-12)

Both surveys so far read clusters of one file. This maps the other twenty-five,
by the same method and for the same reason: the cheapest way to avoid reading
the wrong thing carefully.

Counted at `902937accd7ac67cd8ed16e73b1db2b75cab48a7` by parsing every file for
suite methods (`func (x *Suite) TestX()`), plain tests (`func TestX(t
*testing.T)`) and `.Run(` subtests, and tallying the client calls each file's
bodies make.

| file | lines | cases | top client calls | read? |
|---|---:|---:|---|---|
| `integration_test.go` | 11,171 | **257** | ExecuteWorkflow 141, SignalWorkflow 47, UpdateWorkflow 45, GetWorkflowHistory 34 | 47 of 257 |
| `nexus_test.go` | 4,239 | 32 | ExecuteOperation 14 | no — Nexus |
| `external_storage_test.go` | 1,610 | 32 | ExecuteWorkflow 25, SignalWorkflow 7, QueryWorkflow 4 | **no — candidate** |
| `payload_limits_test.go` | 1,027 | 19 | ExecuteWorkflow 17, CancelWorkflow 6, SignalWorkflow 4 | **no — candidate** |
| `worker_deployment_test.go` | 1,704 | 18 | WorkerDeploymentClient 19 | no |
| `worker_versioning_test.go` | 1,153 | 17 | UpdateWorkerVersioningRules 23 | no |
| `worker_heartbeat_test.go` | 1,165 | 16 | ExecuteWorkflow 10 | no |
| `workflow_random_test.go` | 252 | 6 | ResetWorkflowExecution 2 | no |
| `worker_tuner_test.go` | 157 | 6 | — | no |
| everything else (17 files) | | 26 between them | | no |

429 test functions in the directory, counted the same way in every file.
Subtests are **not** folded in here — `integration_test.go` alone carries 41
`.Run(` calls — so these are functions, which is a lower bound on collected
cases and the only figure that is comparable across files without reading them.

**`workflow_test.go` is the second-largest file in the directory — 4,702 lines —
and contains ZERO test cases.** It is the workflow *definitions* the other files
execute. A reader ranking by size, or by a name that sounds like the heart of
the suite, would spend a long session there and find nothing to port. That is
this document's "file names did not predict yield" caution, in the same
repository it was written about, at the top of the list.

### What the map says

**`integration_test.go` is the corpus, not a file in it.** 257 of the **429**
test functions in the whole directory — 60% — and the only file where the ratio of engine
behaviour to Temporal-specific machinery is high. Reading it cluster by cluster
is the right shape and the two surveys should continue that way; the
within-file bucketing table lives in
[the updates survey](temporalio-sdk-go-updates-survey.md).

**Two files outside it are worth reading, and both for the same reason:** they
drive ordinary workflows over the client API and assert on limits and
offloading, which are cleat surfaces that exist and have no port coverage.

- **`external_storage_test.go`** (32 cases). Large payloads offloaded to
  external storage. cleat has a blobstore plugin and `workflow_blob_refs`;
  nothing in any port exercises it.
- **`payload_limits_test.go`** (19 cases). What happens when a payload exceeds
  the limit — at start, at signal, at child start, at completion. cleat has
  `signalMaxBodySize` and a 413 path (the update handler returns one), so the
  *shape* ports even though the limits are configured differently: upstream
  sets `limit.blobSize.error` as dev-server dynamic config, cleat has a
  compiled-in constant.

**Three files are Temporal-shaped and should be skipped rather than read:**
`nexus_test.go` (Nexus has no cleat analogue), `worker_deployment_test.go` and
`worker_versioning_test.go` (19 and 23 calls respectively into
`WorkerDeploymentClient` / `UpdateWorkerVersioningRules`, APIs cleat does not
have — its versioning is `workflow_defs` plus routing rules, a different model
rather than a subset).

**`worker_heartbeat_test.go`** (16 cases) is the uncertain one. cleat
heartbeats, and the reaper that reclaims a stalled worker is real engine
behaviour with real defects filed against it — but upstream's cases assert on a
`WorkerHeartbeat` RPC and a worker-status API cleat has no route for, so the
verdicts may land mostly in *satisfied but unobservable*. Worth a cheap look
before a careful one.

### Cost

The whole map was one `curl` of the directory listing, twenty-six raw fetches
and one parsing pass — a few minutes, against the several hours a file-by-file
read would take to reach the same conclusion about `workflow_test.go` alone.
Doing it before the next cluster rather than after is the only part worth
remembering.

### Correcting that map: both candidates were wrong, and the reason is the method (2026-09-12)

Same day, a few hours later. The section above recommends
`external_storage_test.go` and `payload_limits_test.go` as the two files worth
reading outside `integration_test.go`. **I then read them, and neither is
portable.** Correcting it here rather than quietly, because a recommendation
document that is not corrected is worse than no recommendation.

**`external_storage_test.go` — 32 cases, 0 portable.** Seventeen are
`TestTargetContext_*`, asserting that a storage driver is told *which API call*
triggered a store. The other fifteen assert on counters inside a Go object the
test registered itself:

```go
s.client, _ = s.newDefaultClient(func(o *client.Options) {
    o.ExternalStorage = &converter.ExternalStorageOptions{
        Drivers:              []converter.StorageDriver{s.driver},
        PayloadSizeThreshold: extStoreThreshold,
    }
})
...
storeCount, retrieveCount := s.driver.getStoreCounts()
s.Equal(0, storeCount, "small payloads should never be stored")
```

`converter.StorageDriver` is an **in-process Go interface registered into the
client**, and the assertions read its call counts. A port driving HTTP can
neither register a driver nor read those counters. The model is also different
in kind from cleat's: upstream offloads at the *client* boundary before the
payload reaches the server; cleat's blobstore is a *server-side* plugin. They
are not the same feature seen from two angles.

**`payload_limits_test.go` — 18 cases, none portable as written.** The
distribution, which the name does not give away:

| what the case is about | count |
|---|---:|
| a payload produced INSIDE the workflow exceeding an error limit — workflow result, update result, query result, child input, activity input/result, heartbeat | 10 |
| a payload exceeding a WARNING limit, asserted by reading the client's logger | 7 |
| a bypass case | 1 |

All three need something cleat does not have: configurable `limit.blobSize.warn`
/ `.error` dynamic config, outbound payload checks, and an in-process logger the
test can read (`ts.assertLogContains(logger, payloadErrorMessage)`). The four
cases whose *names* sound inbound — `TestPayloadSizeWarningSignalInput`,
`...UpdateInput`, `...QueryInput`, `...SignalWithStartInput` — are in the
warning group and assert a **log line**, not a refusal.

My earlier sentence, "the *shape* ports even though the limits are configured
differently", was too generous by the whole file.

### What the mistake teaches, which is worth more than the map

**The client-call histogram says how a case is DRIVEN, not what it is ABOUT.**

That is the flaw, stated precisely. `external_storage_test.go` shows
`ExecuteWorkflow:25`, which is what made it look like "drives ordinary workflows
over the client API" — and it does, as *setup*. The subject is a driver
interface. `payload_limits_test.go` shows `ExecuteWorkflow:17, CancelWorkflow:6`
for the same reason.

The updates cluster was a good pick because the two coincided: the cases are
driven by `UpdateWorkflow` and are *about* updates. That coincidence is common
inside `integration_test.go`, whose cases are mostly end-to-end behaviour, and
rare in the specialised files, whose cases drive a workflow in order to observe
something else.

**So the histogram is a first pass and not a verdict.** The cheap second pass,
which would have caught both of these in a minute each, is to read what the
ASSERTIONS touch:

```bash
grep -nE 'ts\.(Equal|True|Error|NoError|Contains)' <file> | head -40
```

If the assertions name client objects, drivers, loggers or counters the test
constructed, the case is about an in-process interface and no HTTP port can
reach it — however ordinary the calls that set it up look. If they name
workflow results, statuses, or server responses, it is reachable.

**The map's other conclusions stand**, and the negative one is unaffected and
still the most useful line in it: `workflow_test.go` is the second-largest file
in the directory and contains zero test cases.

**Revised recommendation: stay inside `integration_test.go`.** Its 210 unread
methods (257 minus the 47 surveyed) are the corpus. The two clusters read so far
yielded **10 gaps** — 3 from schedules, 7 from updates — and **three defects**:
cleat#1297 and cleat#1330 from the cases, and cleat#1331 from the probe the
cases needed. The within-file bucketing has now been right twice and wrong zero
times, because inside that file how a case is driven and what it is about are
usually the same thing.

### What is actually left in `integration_test.go`, with the sampling error stated (2026-09-12)

The section above ends "stay inside `integration_test.go`; 210 unread methods".
That is a count of what has not been read, not of what is worth reading. This
narrows it, using the assertion-level check the correction above proposed — and
the honest headline is that **the check is better than call-counting and still
needs a sample.**

Two passes over the 209 unread methods:

| pass | what it matched | "reachable" |
|---|---|---|
| assertion arguments only | text inside `ts.Equal(...)` etc. | 144 |
| **whole body** | any marker anywhere in the case | **87** |

The first pass is wrong by 57 cases and wrong in the flattering direction, for a
reason worth naming: a case that **constructs a worker** (`worker.New(...)` with
options, `ts.worker.Stop()`, `RegisterWorkflowWithOptions`) asserts on perfectly
ordinary run outcomes, so its assertions look portable while its *setup* is
unreachable. That is 52 of the 57. Reading assertions is necessary and not
sufficient; the unreachable machinery can be anywhere in the body.

Whole-body result:

| bucket | count |
|---|---:|
| reachable from an HTTP port | **87** |
| constructs or steers a worker | 52 |
| in-process activity log / tracer / metrics assertions | 35 |
| local activities | 14 |
| history event internals | 8 |
| raw gRPC (`WorkflowService()`, `OperatorService()`) | 6 |
| nexus | 5 |
| interceptors | 2 |

### And 87 is still an over-count — here is the sample that says so

"Reachable" is the **fallback** bucket: a case lands there by matching no
exclusion marker, which is exactly the shape that accumulates false positives.
A random sample of eight, read individually:

| case | verdict |
|---|---|
| `TestContinueAsNewCarryOver` | portable |
| `TestCancellationWithOptions` | portable |
| `TestWorkflowIDReuseIgnoreDuplicateWhileRunning` | portable (and partly covered by `duplicate_start_test.go`) |
| `TestSelectorNoBlock` | maybe — `workflow.Selector` has a cleat analogue in `cleat/selector.go` |
| `TestStackTraceQuery` | no — `QueryTypeStackTrace`, and cleat removed query handlers |
| `TestContextPropagator` | no — SDK context propagation |
| `TestSlotSuppliersWithSessionAndOneConcurrentMax` | no — worker tuner and sessions |
| `TestSignalWithStartWorkflowTypedSearchAttributes` | no — cleat has neither half |

Three clearly portable, one uncertain, four not. **So the defensible estimate is
30–40 portable cases remaining, not 87** — and that figure is from a sample of
eight, which is enough to say the fallback bucket is inflated and not enough to
put a decimal on it.

Stating it this way rather than quoting 87 because this document's own history
is what happens when a count is published before it is enumerated, and because
the last two numbers it carried were both corrected within hours.

### Where the remaining yield is concentrated

From the sample and the bucket names, the portable residue clusters around
**continue-as-new**, **cancellation semantics** and **signal delivery** — cleat
surfaces that exist, have HTTP routes, and whose upstream cases assert on run
outcomes rather than on worker internals. That matches where the first two
surveys found their gaps.

**Not** worth a cluster of its own: `GetWorkflowHistory`. It looks like one — 34
call sites, the fourth-largest surface in the file — and of the 25 cases that
call it, **17 assert on run outcomes and only 8 on history contents**. History is
those cases' *setup*, not their subject, which is the driven-versus-about
distinction one level down. There is no history cluster to port; the eight real
ones assert on Temporal event types.

### Where the residue actually is, and the check every estimate so far has been missing (2026-09-12)

The section above names the remaining yield as clustering around "continue-as-new,
cancellation and signal delivery", from a **sample of eight**. Bucketing all 87
candidates by subject says two of those three are wrong, and the reason is a
blind spot that applies to every yield figure in this document.

| subject | candidates | verdict |
|---|---:|---|
| *other* (panics, deadlock detection, heartbeats, determinism) | **39** | unexamined — the fallback bucket again |
| cancellation | **15** | the largest real cluster |
| child workflows | 10 | overlaps `samples-go`'s child tests |
| query | 5 | cleat removed query handlers; mostly not portable |
| signals | 4 | two need search attributes or signal-with-start |
| side effects | 4 | worth a look |
| **continue-as-new** | **3** | **yields approximately zero** — see below |
| memo / search attributes | 3 | cleat has neither |
| retry, terminate, await, selector | 1 each | |

**Continue-as-new was the clearest of my three named clusters and is the emptiest.**
Read case by case:

- `TestContinueAsNew` — every iteration runs, result is 999. **Already asserted
  twice**: `ports/dbos-transact-py/tests/test_continue_as_new.py::test_a_workflow_can_continue_as_new_and_every_iteration_runs`
  and `ports/samples-go/tests/child_continue_as_new_test.go::TestEveryIterationOfAContinuedChildRuns`.
- `TestContinueAsNewCarryOver` — Memo, SearchAttributes and RetryPolicy carried
  across the boundary. cleat has none of the three.
- `TestContinueAsNewOmitsUnsetSearchAttributes`, `TestContinueAsNewWithRetryPolicy` —
  same, plus `ts.activities.invoked()`, which is in-process.

### The blind spot: nothing here can see that two ports assert the same property

Ported tests in this repo name their upstream case in a docstring, and a
mechanical check exploits that. Run against the 87 candidates, **3 are named
verbatim in an existing port test** — all three from the `TestWorkflowIDReuse*`
work, ported from the same upstream.

That number is worthless as a duplication estimate, and the reason is structural:
**each port cites ITS OWN upstream's case names.**
`test_a_workflow_can_continue_as_new_and_every_iteration_runs` asserts exactly
what `TestContinueAsNew` asserts and shares not one identifier with it. Four
ports, four vocabularies, one property.

So every yield figure this document has carried — 33, 18, 2–4, 87, 30–40 — has
counted *upstream cases not yet ported from that upstream*, never *properties
not yet asserted anywhere*. The two differ by however much the four upstreams
overlap, and on the one cluster measured by hand they differ by the whole
cluster.

**The check that works is by subject and it is manual.** Bucket the candidates,
then for each bucket read what the existing ports already assert — `grep -rli
<concept> ports/*/tests/` takes a second and gives the files to read. It is the
step between "cleat has this surface" and "this case is worth porting", and it
has been missing from every survey here including both of mine.

### Revised, and stated as a lower bound this time

**Cancellation (15) and the 39-case *other* bucket are where the remaining yield
is**, and neither has been read. Cancellation in particular needs the
cross-port check before anyone starts: `grep -rli cancel ports/*/tests/` returns
**fourteen files** across all four ports, so the overlap there is likely to be
larger than for continue-as-new, not smaller.

No new number is offered. The honest statement is that **30–40 was an upper
bound that ignored cross-port overlap**, the one cluster measured against that
overlap lost all of it, and the next person should read the cancellation bucket
against `ports/dbos-transact-py/tests/test_cancellation.py`,
`test_cancel_propagation.py`, `test_bulk_cancel.py` and
`ports/samples-go/tests/terminal_statuses_test.go` before writing anything.

**Done, in [`temporalio-sdk-go-cancellation-survey.md`](temporalio-sdk-go-cancellation-survey.md).**
Fifteen cases: **7 already asserted elsewhere, 1 gap filed (cleat#1351), 1 gap
portable, 6 not portable.** The seven were covered by two ports from two
different upstreams and **a name-based duplication check reports zero overlap
among them** — the prediction above, confirmed on the first cluster it was
applied to. The cross-port check cost about ten minutes and turned a cluster of
fifteen into two cases worth acting on.

### The 39-case "other" bucket, triaged (2026-09-12)

The bucketing above left *other* as the largest unread group. Read by name and
then cross-checked, it is mostly not portable and contains **one** clean case:

| what they are about | count | verdict |
|---|---:|---|
| the `TestWorkflowIDReuse*` / conflict-policy cluster | 6 | already surveyed with the updates cluster |
| OpenTelemetry / OpenTracing tracing and baggage | 6 | not portable — in-process tracers |
| activities and local activities | 7 | not portable — cleat has durable calls, not activities |
| worker internals: pollers, slot suppliers, fatal-error-on-start, task-queue priority | 5 | not portable |
| SDK internals: context propagators, `RawValue`, arity errors, client run-following | 4 | not portable |
| non-determinism detection | 3 | covered — `samples-go/tests/nondeterminism_test.go`, `dbos-transact-py/tests/test_determinism.py` |
| reset, versioning loop, root workflow, cancel details, deadlock detection | 5 | not portable — cleat has no reset, no root-workflow id, no cancel details, and **no workflow deadlock detector** (the only `deadlock` hits in `engine/` are database retry predicates) |
| update ordering, failure metrics | 2 | overlaps the update port / needs an in-process metrics handler |
| **`TestPanicFailWorkflow`** | **1** | **gap, ported** |

**The cross-port check is what made the panic case visible, and it is a single
grep: `grep -rli panic ports/*/tests/` returns NOTHING.** A guest panic is about
as fundamental as engine behaviour gets — it is what happens when workflow code
is simply wrong — and across four ports and roughly two hundred cases, no test
asserted anything about it.

Measured before porting: cleat answers `status: "failed"` and carries the panic's
own text through to `error`. So it passes upstream's assertion, and
`ports/temporalio-sdk-go/tests/panic_test.go` pins it.

**Running total for `integration_test.go`:** 47 surveyed in the first two
clusters, 15 in cancellation, 39 here — **101 of 257**. The remaining clusters
this table has not reached are child workflows (10), query (5), signals (4) and
side effects (4), plus the methods the reachability pass excluded.
