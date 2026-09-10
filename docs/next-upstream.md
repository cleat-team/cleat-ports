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
| `test_failures.py` | 37 | 5 |
| `test_scheduler.py` | 35 | 5 |
| `test_client.py` | 57 | 3 |
| `test_async.py` | 33 | 1 |
| `test_concurrency.py` | 11 | 1 |
| `test_workflow_management.py` | 46 | 1 |
| `test_queue.py` | 91 | 0 |
| **total** | **371** | **33 → 25 → 18** |

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
