# `durabletask-go` — `tests/orchestrations_test.go`, case by case

Companion to `next-upstream.md`, which recommended this project and **predicted**
a yield for this file. This replaces the prediction with a reading. Read at
`3fe35d93fe1d2bdab21a3d85c14867532adef0b0`, 1492 lines.

Nothing here is ported. `ports/durabletask-go/` does not exist, and this
deliberately does not create it: `Makefile`'s `PORTS := $(notdir $(wildcard
ports/*))` would add an empty directory to the CI matrix and every job would
fail on a port with no harness. Scaffolding is `docs/adding-a-port.md`'s job.

---

## The denominator is 30, not 26

`next-upstream.md` says 26 for this file. That is the **function** count. Four
functions carry `for _, x := range []bool{true, false}` with a `t.Run` inside,
so each contributes two collected cases:

    Test_ExternalEventTimeout                                                 x2
    Test_TerminateOrchestration_Recursive                                     x2
    Test_TerminateOrchestration_Recursive_TerminateCompletedSubOrchestration  x2
    Test_PurgeOrchestration_Recursive                                         x2
    22 plain + 4x2 = 30

Derived independently of the correction that reported it, by walking the file
and attributing each loop to its enclosing function:

    python3 - tests/orchestrations_test.go <<'EOF'
    import re, sys
    lines = open(sys.argv[1]).read().split('\n')
    funcs = [(i+1, m.group(1)) for i, l in enumerate(lines)
             if (m := re.match(r'^func (Test\w+)\(', l))]
    total = 0
    for k, (ln, name) in enumerate(funcs):
        end = funcs[k+1][0]-1 if k+1 < len(funcs) else len(lines)
        total += 2 if any(re.search(r'for _, \w+ := range \[\]bool', l)
                          for l in lines[ln:end]) else 1
    print(len(funcs), "functions,", total, "collected cases")
    EOF

**Both `grep -c '^func Test'` and a deduplicated name count give 26**, and both
are wrong in the same direction — the same defs-versus-collected error the dbos
work-lists were already carrying. Two derivations agreeing is not evidence when
they count the same thing.

## 17 of 26 functions assert OpenTelemetry span sequences

`assertSpanSequence` appears in 17 of the 26. **This does not make them
untranslatable**, and that is worth saying plainly because the surface reading is
that a third of the file is about tracing: every one of the 17 also carries
between 4 and 11 assertions that are not about spans — status, output, ordering,
timestamps. The span half is *additional*.

But it is a real cost. A port that reproduced the span assertions would need OTel
collection in the harness, which nothing here has. **Every "portable" below means
the engine assertions, with the span sequence dropped**, and that is a narrowing
this document is choosing rather than a fact about the upstream file.

## How much of this was read, and how

The dbos surveys went 17 → 9 → 2 on re-reading, every time because names and
outlines were classified as if they were bodies. So, explicitly:

* **Read in full** (5): `Test_TerminateOrchestration_Recursive`,
  `Test_SingleActivity_ReuseInstanceIDIgnore`, `Test_EmptyOrchestration`,
  `Test_SingleTimer`, `Test_ConcurrentTimers`.
* **Read as extracted assertion cores** (6): `Test_IsReplaying`,
  `Test_ExternalEventContention`, `Test_SuspendResumeOrchestration`,
  `Test_PurgeCompletedOrchestration`, `Test_PurgeOrchestration_Recursive`,
  `Test_RecreateCompletedOrchestration` — every `assert`/`require` line and every
  client call, in order, with the orchestrator bodies not read.
* **Classified from signature and name** (the rest): the activity/timer/
  sub-orchestration block, `Test_ActivityChain` through
  `Test_SingleSubOrchestrator_Failed_Retries`.

**The third group is the one to distrust.** It is the method that produced every
number this repo has had to retract.

---

## The headline: `next-upstream.md` and ISSUES 29 are the wrong lens for the recursion cases

`next-upstream.md` classifies the six recursion cases against **ISSUES 29**,
which said cleat's cancellation is `WHERE id = $1` with no `parent_workflow_id`
traversal, and treats them as probing an open question.

**That description of ISSUES 29 is out of date as of 2026-09-09** — the entry
has been rewritten twice and measured. `WHERE id = $1` is true of
`CancelWorkflow` and false of the engine: `enforceParentClosePolicy` has a
`REQUEST_CANCEL` arm that does traverse `parent_workflow_id`. The section below
is unaffected — its point is that ISSUES 29 is about *cancel* while four of the
six cases are about *terminate*, and that stands. It is now understated if
anything, since cancel has a cascade of its own.

ISSUES 29 is about **cancel**. Four of the six are about **terminate**, and
cleat's terminate is a different mechanism that ISSUES 29 does not describe.

**cleat already has a configurable cascade.** `parent_close_policy` is a column
on `workflow_instances` with three legal values — `ABANDON` (the default),
`TERMINATE`, `REQUEST_CANCEL` — validated by `engine.ValidateParentClosePolicy`,
indexed by `idx_instances_parent_policy`, and enforced by
`enforceParentClosePolicy`, which runs a per-arm `UPDATE ... WHERE
parent_workflow_id = $1 AND parent_close_policy = '<arm>'` on all three dialects.

So upstream's `WithRecursiveTerminate(true|false)` is **expressible in cleat
today**, with the decision in a different place: upstream decides at the
*terminate call*, cleat at the *child spawn*. A `recurse=true` fixture is
children spawned `TERMINATE`; `recurse=false` is the default `ABANDON`. Both
branches of upstream's parametrised assertion have a cleat counterpart.

**Nothing in this repository asserts any of it.** `grep -rl 'parent_close\|ABANDON'`
over `ports/dbos-transact-py/tests/` and `workflows/` returns nothing.

### The part that is a real question, and it is sharper than ISSUES 29

`Test_TerminateOrchestration_Recursive` builds **three** levels — Root → 5× L1 →
one L2 each, eleven orchestrations — and asserts
`assert.NotEqual(t, recurse, executedActivity)`: with recursion the L2 activity
must never run, without it, it must.

cleat's cascade is one level of SQL. A `TERMINATE` child is set to
`status = 'failed'` **directly by that UPDATE**, which does not go through
`FailWorkflow` — and `FailWorkflow` is what calls `enforceParentClosePolicy` for
the next level down. The one arm that does continue is the defer-phase arm: it
sets `status = 'terminating'`, and that child is finalised later through a path
that can cascade again.

**Read that way, a grandchild is reached only if the intermediate child owed a
defer phase.** Depth would then depend on whether a middle workflow happened to
have defers, which is not a property anyone would choose.

**This is a reading, not a measurement, and it is exactly the shape that has been
wrong before.** The blank-`Idempotency-Key` prediction in
`ports/dbos-transact-py/worklists/test-client.md` had three correct file:line
citations, a chain with no branch in it, and a false conclusion, because the
chain had a hop nobody knew to look for. **Do not file this.** A three-level
`TERMINATE` fixture settles it in one run and is the single highest-value case in
this file.

---

## Classification

**Portable, and novel here** — cleat has the surface and nothing in this repo
asserts the property:

| case | why it is worth having |
|---|---|
| `Test_TerminateOrchestration_Recursive` ×2 | three-level `TERMINATE` vs `ABANDON`; settles the depth question above |
| `Test_TerminateOrchestration_Recursive_TerminateCompletedSubOrchestration` ×2 | the same, where a sub-orchestration has already completed — cleat's arms carry `AND status NOT IN ('done','failed')`, so the completed child is exactly the row those predicates exclude |
| ~~`Test_RecreateCompletedOrchestration`~~ | **already covered — this row was stale.** `ports/dbos-transact-py/tests/test_queues.py::test_a_completed_run_still_answers_for_its_idempotency_key` asserts cleat's side of exactly this divergence, side-effect count and all, and predates the survey. Checked 2026-09-10 while picking work off this table |
| `Test_SingleActivity_ReuseInstanceIDIgnore` | **PORTED** — `ports/durabletask-go/tests/reuse_id_test.go`. Upstream's opt-in `IGNORE` is cleat's only policy, so the selection half does not port and the behaviour half does. The two novel assertions are that the surviving run keeps the **first** start's *input* and its *`created_at`*; the existing dedup tests send identical payloads on both starts and structurally cannot see either |
| `Test_ExternalEventTimeout` ×2 | event-or-timeout, both branches, in one fixture |
| `Test_ContinueAsNew_Events` | events carried across a continue-as-new boundary — **CLAIMED 2026-09-09 by session `01UbTiXNC2rGrEbBheCUkd57`**, and it lands as a divergence rather than a port: upstream's `WithKeepUnprocessedEvents()` is opt-in and cleat has no counterpart. `ContinueAsNew` never touches `workflow_signals` on any of the three dialects, and the table is keyed by `workflow_id`, so an unconsumed signal stays on the old run. Porting the assertion cleat *can* answer |
| `Test_ExternalEventContention` | three events raised, ordering across a continue-as-new |

**Declines — cleat has no counterpart:**

| case | what is missing |
|---|---|
| `Test_PurgeCompletedOrchestration` | there is no purge-a-run API. `PurgeWorkflowDef` purges a *definition*; a run's history goes only through the time-based retention sweep, which no caller invokes |
| `Test_PurgeOrchestration_Recursive` ×2 | same, plus recursion |
| `Test_SuspendResumeOrchestration` | no operator-initiated suspend. cleat suspends on awaits; `cancel` is terminal by design and `resume` is deliberately rejected. Probes a decision cleat has made rather than a gap |
| `Test_IsReplaying` | no is-replaying surface exists — not a host call, not a field. cleat's analyzer refuses non-deterministic constructs at build time instead of exposing replay state at run time |
| `Test_ConcurrentTimers` | creates three timers, then awaits them. cleat's `DurableSleepMs` blocks; there is no timer *handle* to hold and await later |
| `Test_SingleActivity_ReuseInstanceIDTerminate` | no "terminate the running one and start fresh" policy |
| `Test_SingleActivity_ReuseInstanceIDError` | no "reject if the id is in use" policy — cleat has exactly one reuse behaviour, and it is IGNORE |

**Already asserted by the dbos port** — a second phrasing of something covered;
low value unless the phrasing is better. `Test_EmptyOrchestration`,
`Test_SingleTimer`, `Test_SingleActivity`, `Test_ActivityChain`,
`Test_ActivityRetries`, `Test_ActivityFanOut`,
`Test_SingleSubOrchestrator_{Completed,Failed,Failed_Retries}`,
`Test_ContinueAsNew`, `Test_ExternalEventOrchestration`,
`Test_TerminateOrchestration`.

**These twelve are the group classified from signature and name.** The bucket is
a judgement that `tests/test_retries.py`, `test_children.py`, `test_defer.py`,
`test_continue_as_new.py` and `test_signals.py` already assert these properties.
It has **not** been checked case by case against those files, and that check is
the first thing to do before anyone treats the number below as a backlog.

### The check, done 2026-09-09 — the bucket is 8, not 12, and it moves UP

Read each of the twelve at `3fe35d9` against this port's tests. **Four do not
belong in this bucket**, and the correction runs in the opposite direction from
the one this document warned about.

| upstream case | verdict |
|---|---|
| `Test_EmptyOrchestration` | covered |
| `Test_SingleTimer` | **split — the timestamp half was wrongly declined, see below** |
| `Test_SingleActivity` | **split — the unicode half is UNCOVERED** |
| `Test_ActivityChain` | covered |
| `Test_ActivityRetries` | covered — `test_retries.py::test_a_retryable_failure_is_retried_with_backoff` |
| `Test_ActivityFanOut` | covered — order *and* parallelism, see below |
| `Test_SingleSubOrchestrator_Completed` | covered |
| `Test_SingleSubOrchestrator_Failed` | **UNCOVERED** |
| `Test_SingleSubOrchestrator_Failed_Retries` | **UNCOVERED** |
| `Test_ContinueAsNew` | covered |
| `Test_ExternalEventOrchestration` | covered |
| `Test_TerminateOrchestration` | covered — `test_workflow_management.py::test_force_complete_moves_a_running_workflow_to_done` |

**The two clean misses: nothing in this port has a child that FAILS.** All five
cases in `tests/test_children.py` use successful children, and the only
error-shaped assertion is `assert not r.get("error")` — the *absence* of one.
`Test_SingleSubOrchestrator_Failed` asserts the opposite direction: the child's
message reaches the parent's failure details
(`assert.Contains(metadata.FailureDetails.ErrorMessage, "Child failed")`). The
retries variant asserts the same after the child has exhausted a policy.

Both are portable — cleat has children, child failure, and an error field on the
parent — and both are novel. This is the single largest gap the check found and
it was invisible from the case names, which say `SingleSubOrchestrator` and look
like the `Completed` case that *is* covered.

**`Test_SingleActivity` is two assertions and only one of them is covered.** The
completion and the output value are; the output value is `"Hello, 世界!"`, and
**no test in this port puts a non-ASCII byte in a workflow input or an asserted
result.** Checked mechanically: 46 lines contain non-ASCII and every one is an
em-dash in prose.

This is *not* the limitation `test_scheduling.py` already records. That one is
real and is about the **fixture key channel** — keys travel in a URL path and
`http.client` encodes the request line as ASCII, so a non-ASCII key raises
`UnicodeEncodeError` in the test process. A workflow **result** travels in a JSON
body and is not affected. Different channel, and the existing note explicitly
calls itself "a limit of the instrument rather than a judgement that unicode is
uninteresting".

**`Test_SingleTimer`'s timestamp half — I declined this and was wrong.**

I wrote that it asserts `metadata.LastUpdatedAt >= metadata.CreatedAt`, that
cleat records no start time, and that `GET /api/workflows/:id` returns
`created_at` as `0001-01-01T00:00:00Z`, citing ISSUES 30. The last part I had
*measured*, which is why I believed the rest.

**The measurement was against a binary fifteen hours old.** ISSUES 30 was true
when written and both halves were fixed the same day: cleat#1094 added
`started_at` on all three dialects, and cleat#1106 fixed `GetWorkflowByID`,
which had been selecting `created_at` and four other fields into locals without
assigning them — so the LIST endpoint returned the true value while the single
GET returned the zero time.

Against current `develop`: `created_at` 00:15:06.179793, `started_at` .187747,
`completed_at` .536338. The ordering is fully askable, and it is now asserted in
`tests/test_run_clock.py` — along with the endpoint disagreement itself, which
is invisible from either endpoint alone.

So this moves out of the declines. **The declines are 8 again, not 9**, and the
lesson is narrower than "check the entry": a port measures whatever binary the
harness last installed, so a finding derived from it dates from that build
rather than from `develop`. `bin/.cleat-build` names the sha.

**`Test_ActivityFanOut` is fully covered and worth saying why**, because it was
the one I expected to fail. It asserts a specific output ordering and a duration
bound. `test_children.py::test_await_all_children_returns_every_child_s_own_result`
pins `tags == ["child-0", "child-1", "child-2"]` — spawn order, not completion
order — and `test_parallelism.py` pins peak concurrency above 1 and at least 3.
Between them both halves are asserted.

### What this does to the totals

    before        8 declines · 10 portable and novel · 12 unverified
    after check   9 declines · 12 portable and novel ·  8 verified as covered
    after fix     8 declines · 12 portable and novel ·  8 verified, 1 now ported

The middle line stood for about an hour. `Test_SingleTimer` went into the
declines on a measurement taken against a stale binary; its timestamp half is
askable and is now ported.

**The direction is the finding.** This document warned that the 12 must not be
added to the 10 because the dbos `test_dbos.py` figure went 17 → 9 → 2 as it was
read — an "already covered" bucket shrinking a gap that was really there. Here
it went the other way: the bucket was too *generous* about what this port
already asserts, and reading it made the backlog bigger.

So the warning was right that the number was unreliable and wrong about which
way. Worth recording, because "assume the optimistic number is optimistic" is
itself a heuristic that can point the wrong way, and the only fix for either is
to read the cases.

### What was NOT done

Each verdict rests on reading the upstream assertions and grepping this port for
an equivalent. **No test was run to confirm a "covered" verdict actually passes
for the reason claimed**, and a test can assert a property while passing for an
unrelated one. The two UNCOVERED verdicts are the stronger claims here: they
rest on absence, which a grep establishes better than presence.

---

## What this adds up to, and what it does not

**8 declines. 10 portable and novel. 12 unverified as already-covered.**

The 10 is the only figure with a body read behind it, and even there four of the
ten come from the extracted-assertions group rather than a full read.

**The 12 is not a portable count and must not be added to the 10.** If the
already-covered judgement is wrong for even a few, they move into the portable
bucket — which is how the dbos `test_dbos.py` figure went from 17 to 9 to 2, in
the other direction.

**What is safe to conclude:** the recursion cluster is real, uncovered, and
sharper than the open question this repo already has about it. That is a better
reason to build the port than any total.
