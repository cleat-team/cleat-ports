# dbos-transact-py: findings

Findings discovered by porting this suite. Each entry gets promoted to a core
regression test, or gets classified as a design difference and stays here — see
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

Empty is the correct starting state. Add entries as you port, not at the end.

**This file was backfilled on 2026-09-07, and that was a mistake worth naming.**
Nineteen findings were recorded straight onto core issues and PRs while this
file stayed empty, so for two days the port's own answer to "what has this
already found?" was "nothing". Every entry below was reconstructed after the
fact from the core tracker, which is why several say less about the upstream
assertion than they would have if written at the time. Add entries as you port.

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

---

# Findings

A total written here rots the moment an entry is added, so read each entry's
own **Status** line rather than a number in this header. Every entry carries
one. Re-derive both figures with a single pass:

    awk '/^## [0-9]+\. /{n++} /\*\*Status:\*\*/{if(n)s++} \
      END{print n" entries, "s" carry a status"}' ports/dbos-transact-py/issues/*.md

**That path is `issues/*.md` and it used to be this file.** The 2026-09-09 split
moved every entry out; run against `ISSUES.md` the command now prints

    " entries,  carry a status"

-- two blank fields, because `n` and `s` are never set. Not an error, not a zero:
a published command that silently answers nothing. It was the header's own
re-derivation, which is the one command in this file a reader is most likely to
trust without checking.

**Do not anchor that grep at `^`, and this paragraph is the reason.** It used
to say nine of twenty-six entries carried a status, "the field arrived with
the template and most entries predate it". Both halves were wrong. **Nineteen
entries write it INLINE** — `**Class:** Bug · **Status:** Promoted (…)` — where
a `^`-anchored pattern cannot see it, and the ninth match was the template's
own example line, which is not an entry at all. So the published census
under-reported by nineteen and over-reported by one, and a session was sent to
reconcile eighteen entries that were already reconciled.
The `if(n)` above is what skips the template.

Class is `Bug` unless stated. "Promoted" here means a regression test that gates
merges in `cleat-team/cleat`, in the package it guards — see step 4 of
[../../docs/promotion-checklist.md](../../docs/promotion-checklist.md).

## The entries

One file per entry, under `issues/`. They were a single appended file until
2026-09-09: every addition collided with every other as an end-of-file append,
and entry numbers were assigned by hand from whatever the writer's branch had
last seen, which produced two collisions and one piece of wrong advice in a
single day.

**The number stays in the filename.** There are 56 references of the form
`ISSUES.md 26` across fourteen files and three languages -- `ci.yml`, the guard
itself, four Python tests and three Go files under `ports/samples-go/`, one of
them a workflow fixture. Nothing verifies that any of them resolves, in either
scheme, so a slug-only rename would be 56 silent breakages rather than a tidier
tree.

This table is generated, and `scripts/check-issue-numbers.sh` fails if it drifts
from `issues/`. An index that quietly stops listing an entry is the same defect
as a guard that stopped seeing this file at all: everything downstream reads the
index, so an entry missing from it is an entry nobody finds.

| # | Entry |
|---:|---|
| 1 | [Seven API routes were registered on a table the binary never used](issues/001-seven-api-routes-were-registered-on-a-table-the-binary-nev.md) |
| 2 | [An admin API refusal answered 500](issues/002-an-admin-api-refusal-answered-500.md) |
| 3 | [Three host calls dropped work past the end of replay history](issues/003-three-host-calls-dropped-work-past-the-end-of-replay-histo.md) |
| 4 | [`cleat vet` accepted an entry point taking a single string](issues/004-cleat-vet-accepted-an-entry-point-taking-a-single-string.md) |
| 5 | [A suspending segment discarded the query state it was carrying](issues/005-a-suspending-segment-discarded-the-query-state-it-was-carr.md) |
| 6 | [A completing child rewrote its parent's event and left the checksum stale](issues/006-a-completing-child-rewrote-its-parent-s-event-and-left-the.md) |
| 7 | [`ParentClosePolicy TERMINATE` did not terminate a child a worker held](issues/007-parentclosepolicy-terminate-did-not-terminate-a-child-a-wo.md) |
| 8 | [A zero `MaxInterval` meant "a maximum of zero"](issues/008-a-zero-maxinterval-meant-a-maximum-of-zero.md) |
| 9 | [`deploy-workflow` ignored the version embedded in the WASM](issues/009-deploy-workflow-ignored-the-version-embedded-in-the-wasm.md) |
| 10 | [A policy-terminated child recorded no `completed_at`](issues/010-a-policy-terminated-child-recorded-no-completed-at.md) |
| 11 | [API key creation emitted PostgreSQL SQL to every dialect](issues/011-api-key-creation-emitted-postgresql-sql-to-every-dialect.md) |
| 12 | [On MySQL, API keys are written to one database and read from another](issues/012-on-mysql-api-keys-are-written-to-one-database-and-read-fro.md) |
| 13 | [A workflow whose only host call was `PluginCallStreaming` did not compile](issues/013-a-workflow-whose-only-host-call-was-plugincallstreaming-di.md) |
| 14 | [The streaming plugin registry was built, filled, and never given to the engine](issues/014-the-streaming-plugin-registry-was-built-filled-and-never-g.md) |
| 15 | [`PollChild` is not replayed](issues/015-pollchild-is-not-replayed.md) |
| 16 | [`PollSignal` is not replayed](issues/016-pollsignal-is-not-replayed.md) |
| 17 | [A continue-as-new chain is unfollowable](issues/017-a-continue-as-new-chain-is-unfollowable.md) |
| 18 | [Workflow updates are accepted with a 202 and never delivered](issues/018-workflow-updates-are-accepted-with-a-202-and-never-deliver.md) |
| 19 | [`DurableCallWithHeartbeat`'s `onProgress` could never fire](issues/019-durablecallwithheartbeat-s-onprogress-could-never-fire.md) |
| 20 | [cleat has no work queues, so most of the upstream queue suite is unportable](issues/020-cleat-has-no-work-queues-so-most-of-the-upstream-queue-sui.md) |
| 21 | [Cancellation is a flag, not a state — so there is nothing to resume](issues/021-cancellation-is-a-flag-not-a-state-so-there-is-nothing-to-.md) |
| 22 | [Concurrent steps inside a workflow are refused by the determinism analyzer](issues/022-concurrent-steps-inside-a-workflow-are-refused-by-the-dete.md) |
| 23 | [Nothing can ask cleat to remove a workflow record](issues/023-nothing-can-ask-cleat-to-remove-a-workflow-record.md) |
| 24 | [A workflow result the store cannot hold is replaced with `{}` and the run reports success](issues/024-a-workflow-result-the-store-cannot-hold-is-replaced-with-a.md) |
| 25 | [A workflow's timeout is a worker-wide flag, not a per-run value](issues/025-a-workflow-s-timeout-is-a-worker-wide-flag-not-a-per-run-v.md) |
| 26 | [Nothing records which worker ran a completed workflow](issues/026-nothing-records-which-worker-ran-a-completed-workflow.md) |
| 27 | [Repeated reclaim is counted but never bounded — dead-lettering is decided on a different axis](issues/027-repeated-reclaim-is-counted-but-never-bounded-dead-letteri.md) |
| 28 | [A workflow's readers are all keyed — nothing can enumerate what it published](issues/028-a-workflow-s-readers-are-all-keyed-nothing-can-enumerate-w.md) |
| 29 | [Cancelling a parent does not stop it, and reaches only opt-in children](issues/029-cancelling-a-parent-does-not-stop-it-and-reaches-only-o.md) |
| 30 | [A run records when it was created and when it finished, never when it started](issues/030-a-run-records-when-it-was-created-and-when-it-finished-nev.md) |
| 31 | [A caller cannot enqueue a workflow inside its own database transaction](issues/031-a-caller-cannot-enqueue-a-workflow-inside-its-own-database.md) |
| 32 | [A worker lost mid-backoff resumes its retry early, discarding the remaining wait](issues/032-a-worker-lost-mid-backoff-resumes-its-retry-early-discardi.md) |
| 33 | [A workflow can only ask about its own children, not about an arbitrary workflow](issues/033-a-workflow-can-only-ask-about-its-own-children-not-about-a.md) |
| 34 | [A signal carries no idempotency key, so a re-sent signal is a second signal](issues/034-a-signal-carries-no-idempotency-key-so-a-re-sent-signal-is.md) |
| 35 | [Workflows can be listed but not filtered by id prefix or start time](issues/035-workflows-can-be-listed-but-not-filtered-by-id-prefix-or-s.md) |
