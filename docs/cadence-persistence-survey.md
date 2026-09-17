# Cadence's persistence contract, case by case

Scoping `uber/cadence` as a third upstream, against the four criteria in
[next-upstream.md](next-upstream.md).

**Upstream:** https://github.com/uber/cadence
**Licence:** Apache-2.0, verified by API 2026-09-10. [licensing.md](licensing.md)
governs: this repo re-expresses assertions from prose and never copies.
**Pinned commit:** `c98e64e010409fbaae94cdc19c2e70ee662634b7`

## The headline

**132 test functions across 14 files. Six files were read; eight were not.** Of
the 85 cases in the six, roughly 20 to 27 are portable — the rest is machinery
cleat does not have, which is a finding about cleat's shape rather than a gap in
it. Of the other 47, **three have since been read and 44 remain unassessed.**

| file | cases | portable | why the rest is not |
|---|---:|---:|---|
| `executionManagerTest.go` | 52 | ~15–20 | transfer tasks, zombie state, conflict resolution, replication |
| `historyTaskDLQPersistenceTest.go` | 7 | ~3 | ack-level bookkeeping is a Cadence-internal cursor |
| `historyV2PersistenceTest.go` | 5 | ~2–3 | history *branching* and forking; cleat's history is linear |
| `matchingPersistenceTest.go` | 12 | ~0–1 | task lists; cleat's workers poll `workflow_instances` directly |
| `queuePersistenceTest.go` | 4 | 0 | domain replication queues |
| `shardPersistenceTest.go` | 5 | 0 | cleat does not shard |
| **read** | **85** | **~20–27** | |
| `semaphoreMetadataPersistenceTest.go` | 5 | **unread** | see "The eight files this survey did not read" |
| `semaphoreTasksPersistenceTest.go` | 5 | 2 read | both already covered by cleat — see below |
| `semaphoreTokenPersistenceTest.go` | 4 | 1 read | one real gap: cleat#1172 — see below |
| `dbVisibilityPersistenceTest.go` | 12 | **unread** | |
| `metadataPersistenceV2Test.go` | 7 | **unread** | |
| `domainAuditPersistenceTest.go` | 6 | **unread** | |
| `configStorePersistenceTest.go` | 5 | **unread** | |
| `executionManagerTestForEventsV2.go` | 3 | **unread** | |
| **not fully read** | **47** | **44 unassessed** | 3 semaphore cases have since been read |
| **total** | **132** | | |

## The eight files this survey did not read

**This table used to have six rows, a total of `129`, and no indication that it
was a sample.** It listed six of the directory's fourteen contract-test files
and presented a directory-wide headline over them. A reader — including its
author, a day later — takes it as an enumeration, because that is what a file
column with a total row looks like.

Three numbers, none of which agreed, and the arithmetic is the whole diagnosis:

| | |
|---|---:|
| the six listed rows, summed | **85** |
| the total row as published | **129** |
| all fourteen files, measured | **132** |

The published total was not the sum of its own rows and was not the true total
either. `132 − 129 = 3`, exactly the case count of
`executionManagerTestForEventsV2.go` — the one file in the directory whose name
does not end `PersistenceTest.go`. That is consistent with the headline having
come from a glob that missed it, though the glob was not recorded, so treat it
as the likeliest reconstruction rather than as established.

Re-derive, and note it takes **two** readings that can disagree — a strict one
anchored on a method receiver, and a loose one that over-matches on purpose. On
this directory they agree file-by-file at 132; a strict parse running clean and
a loose parse finding nothing more is evidence, while a strict parse alone is a
claim:

    for f in $(gh api 'repos/uber/cadence/git/trees/<pinned-sha>?recursive=1' \
        --jq '.tree[].path' | grep '^common/persistence/persistence-tests/.*\.go$'); do
      gh api "repos/uber/cadence/contents/$f?ref=<pinned-sha>" --jq .content |
        base64 -d | grep -cE '^func \([A-Za-z_][A-Za-z0-9_]* \*[A-Za-z0-9_]+\) Test'
    done

Exclude `persistenceTestBase.go`, `shared_test.go` and
`visibilitySamplingClient_test.go`: helpers and unit tests, not contract suites.
That is 17 files in the directory and 14 that carry cases.

**Two readings were needed because the first two attempts under-counted, both in
the same direction.** A receiver pattern of `[A-Za-z]+` excludes digits, so
`*MetadataPersistenceSuiteV2` matched nothing and its file read as **0**; and
assuming the receiver variable is `s` did the same to a file that uses another
name. Both errors report a populated file as empty — they make the survey look
*more* complete, not less, which is why neither announced itself.

### READ 2026-09-16: the semaphore suites yield ZERO, and visibility is the next read

**All fourteen semaphore cases are now read, at the pinned commit, and none is
both portable and novel.** The recommendation below is superseded; it is kept
because how it was wrong is the point.

| suite | cases | portable & novel | why not |
|---|---:|---:|---|
| `semaphoreMetadataPersistenceTest.go` | 5 | **0** | every case is capacity *declaration* |
| `semaphoreTasksPersistenceTest.go` | 5 | **0** | 2 already covered; 3 are RangeID/bucket sharding |
| `semaphoreTokenPersistenceTest.go` | 4 | **0** | 1 already covered; 3 need N>1 |
| | **14** | **0** | |

**The premise was the error.** This section said the semaphores "are the only
unread group aimed at a cleat surface that **already exists** — `AcquireLock`
and `ReleaseLock`, concurrency keys, and the 409". That surface is a **mutex**,
and Cadence's is a **counting semaphore**. The two are not the same shape:

* Metadata carries `Size: 100, BucketSize: 10` — a declared capacity, a conflict
  on re-declare, and a listing of which semaphores exist. Cleat has no declare
  step at all; a key is conjured by its first acquirer and `concurrency_keys` is
  `key_hash BYTEA PRIMARY KEY`, so N is 1 by construction. All 5 land on
  cleat#1116.
* Tokens are **N pre-seeded rows**, each individually grantable —
  `SeedSemaphoreTokens(TokenIDs)`, then `GrantSemaphoreToken` returning
  `SemaphoreGrantApplied` or `SemaphoreGrantSlotTaken`. With **one** token that
  is exactly cleat's mutex, and `TestGrantAndRelease` — including its
  wrong-owner release — is already covered by
  `ports/dbos-transact-py/tests/test_locks.py:42`,
  `test_a_held_lock_cannot_be_taken_and_is_released`. The other three need two
  or more tokens, or the seed step.

Worth recording for cleat#1116 rather than only here: a system that shipped a
counting semaphore stores it as **per-permit rows plus a declared capacity**,
not as an integer counter. That is the crash-safe shape, and it is corroboration
for the design argument on that issue rather than a new idea.

### Visibility is the next read, and the reason is measured rather than named

| | semaphores | `dbVisibilityPersistenceTest.go` |
|---|---:|---:|
| cases | 14 | 12 |
| portable & novel | **0** | **~8, see scope** |
| issues already yielded | 1 (cleat#1172) | 2 (cleat#1182, cleat#1183) |

The filtering surface those cases exercise **exists in cleat and is actively
growing because of this port**. `engine/store_types.go:353` now carries twelve
fields — `Status, InputContains, ErrorContains, Search, Offset, Limit, DefName,
ErrorCode, IDPrefix, ConcurrencyKey, StartedAfter, StartedBefore` — and its own
comments cite cleat#1183 and cleat#1122 as the port findings that added them.

Read at body level rather than by name: `TestFilteringByCloseStatus` records a
Completed and a Failed execution, lists by `Failed`, and asserts exactly one
result — which is `WorkflowFilter.Status`, and is the shape that produced this
survey's existing "cleat has no `cancelled` status" finding. `TestBasicVisibility`,
`TestVisibilityPagination`, `TestFilteringByType`, `TestFilteringByWorkflowID`,
`TestBasicVisibilityTimeSkew` and `TestGetClosedExecution` map onto `Status`,
`Offset`/`Limit`, `DefName`, `IDPrefix`, `StartedAfter`/`StartedBefore` and a
single-run fetch respectively.

`TestClosedWithoutStarted` records a CLOSE with no prior START and asserts it is
still queryable — Cadence keeps open and closed in separate visibility records,
and cleat's row is created at start, so that one is probably inexpressible rather
than a gap. `TestMultipleUpserts` and `TestUpsertWorkflowExecution` are the same
two-table model and likely go the same way.

**PORTED 2026-09-16: five of the twelve, and the estimate above came down.**
`ports/dbos-transact-py/tests/test_listing_filters.py` carries the status,
def-name, pagination, time-window and id-prefix cases. The "~8" was optimistic
by two or three: `TestCronVisibility` has no counterpart (cleat exposes no cron
or schedule flag on a listed run), `TestFilteringByWorkflowID` asks a question
cleat cannot ask (one id per run, no workflowID/runID split -- the id-prefix
test is named for what it does instead), and `TestGetClosedExecution`'s
not-found-until-closed half is the two-table model again. **No port had any
filtering coverage at all before this** -- only "the list contains a run",
tenant isolation, and a created_at consistency check.

One case corrected the test rather than the engine: the time-window assertion
was written expecting `started_after` to exclude a row created exactly on the
boundary, failed, and was right to. `engine/store_types.go:391` documents a
half-open interval `[after, before)` so adjacent windows tile, and the test now
pins that asymmetry instead.

**Scope of this read, stated because the paragraph below is about exactly this
failure.** All 14 semaphore cases were read as names plus the assertions in their
bodies. The 12 visibility cases were read as names plus the persistence API each
calls, and **two** — `TestFilteringByCloseStatus` and `TestClosedWithoutStarted`
— at body level. So "~8" is a better-grounded estimate than a name-based one and
is still an estimate; the semaphore **0** is not.

### The three semaphore suites are the part worth reading next — SUPERSEDED 2026-09-16

> Kept for its reasoning, not its recommendation: all fourteen were read and yield
> **zero** portable-and-novel cases. See the two sections above. The paragraph below
> about judging 33 unread cases by four file names is the part that survived, and it
> is what redirected this read to visibility.


Fourteen of the forty-seven unread cases are semaphores, and they are the only
unread group aimed at a cleat surface that **already exists**: `AcquireLock` and
`ReleaseLock` (`engine/imports.go`), concurrency keys, and the 409 a key refusal
returns.

**The other five I dismissed by their names, in the same paragraph that refuses
to judge the semaphore cases by theirs.** What I wrote was that visibility,
domain metadata, domain audit and a config store are "Cadence-side machinery, on
the same footing as the sharding and replication the survey already excludes."
That is a judgement about 33 cases nobody has read, made from four file names,
sitting three paragraphs above an argument for why exactly that move is unsafe.

It is also already falsified. `dbVisibilityPersistenceTest.go` is the largest
unread file at 12 cases, and the visibility family has produced real cleat
findings — cleat#1182 and cleat#1183 are both listing-and-filtering gaps, and
three cases read there have yielded two issues against a corpus rate nearer one
in eight.

A related one, reported by the session doing that reading: **cleat has no
`cancelled` status**, so `filter.Status` cannot select cancelled runs as a class.
Cancellation lives in `cancellation_requested` / `cancellation_reason` instead —
precisely the shape a visibility suite asks about and a status filter cannot
express.

**That claim is verified; the enumeration this file first published alongside it
was wrong, and how it was wrong is the more useful half.** The status vocabulary
lives in **two languages** — Go string literals and shipped SQL — and a scan of
either alone returns a set that is wrong in both directions:

| | |
|---|---|
| only in SQL status comparisons | `suspended`, `terminated` |
| only in Go status assignments | `dead_lettered` |
| in both | `done`, `failed`, `ready`, `running`, `terminating` |

The first draft here grepped **postgres SQL only**, and published `pending` as a
workflow status. `pending` is the `DEFAULT` on *other* tables
(`migrations/postgres/001_schema.sql:319,374`) — the scan was never scoped to
`workflow_instances`, so it answered a question about the whole schema and was
read as answering one about workflows. It also missed `dead_lettered`, which
exists only on the Go side, and `terminating`.

So no total is published here: scoping a vocabulary to one table needs more than
either grep, and the load-bearing claim does not need one. *No spelling of
`cancelled` appears as a status in either language* — the seventeen `"cancelled"`
literals in Go are all error strings and error classification (`engine/errors.go`,
`callerror_class_test.go`), never a status assignment.

"Visibility is Cadence machinery" is the inference that misses all of it.

So those five are **unread**, on the same footing as the semaphores, and the
sentence that ranked them is withdrawn rather than softened. The semaphores are
still the suggested next read — they aim at a surface that certainly exists —
but *suggested next* is a claim about order, not about the others' worth.

What is in them, by case name:

| suite | cases |
|---|---|
| `semaphoreMetadataPersistenceTest.go` | create-and-get, a default bucket size, a create **conflict**, get **not-found**, list |
| `semaphoreTasksPersistenceTest.go` | claim a bucket, bucket-state not-found, queue lifecycle, **a stale range id is fenced out**, **buckets are independent** |
| `semaphoreTokenPersistenceTest.go` | grant and release, **the same owner under a different token is rejected**, **seeding is idempotent**, scan a bucket |

The bolded four name a property cleat has an analogue for — fencing on a stale
identifier, independence between keys, idempotent seeding, and a second grant to
a holder.

**Three of the fourteen have since been read, and the result is the argument for
everything below.** Recorded on `cadence-residue.md`; verified here against the
cleat-side tests named:

| case | on reading it |
|---|---|
| `TestGrantSameOwnerDifferentTokenIsRejected` | **a real gap** — cleat#1172 |
| `TestStaleRangeIDIsFencedOut` | **already covered** — `test_a_stale_generation_is_refused_as_a_conflict` |
| `TestBucketsAreIndependent` | **already covered, three times** — `test_distinct_keys_do_not_block_each_other` in both `test_concurrency.py` and `test_locks.py`, plus `test_distinct_keys_do_not_block_across_workers` |

So **11 of the 14 remain unread**, and two of the four properties bolded above as
"cleat has an analogue for" turn out to be properties cleat has already **tested**.

**Both "already covered" verdicts were independently audited in ports#199 and
hold** — that audit asks of each covered verdict whether it is backed by something
that *executed* rather than something that was read, and four of its five held.
Read it before relying on any "already covered" in this file, because the one that
failed did so for a reason no reading catches: the port harness connects as a
PostgreSQL **superuser**, which bypasses `FORCE ROW LEVEL SECURITY` unconditionally,
so a green test can be measuring a system configured such that the thing that
breaks cannot break. *Backed by a passing test* and *backed by a passing test run in
the configuration that matters* are different claims, and only the second is worth
anything.

**No `portable` column, deliberately, and this is not caution for its own sake.**
The bolding above is a *name-level* triage; it says what fourteen functions are
called, not what they assert. cleat's own `CLAUDE.md` records the case that makes
that distinction expensive: `TestFinalizeDeferPhaseIsFencedOnTheClaimAndOnTheMarker`
stayed green with the marker predicate deleted, because what refused the repeated
finalize was the ordinary fence — three cases in one test, three different things
doing the refusing, and the name attributed all three to one.

Publishing a portability estimate off names would be **the same defect this
section exists to correct**, one layer in: a table that reads as an assessment of
something nobody examined. The estimate is owed a reading.

**And the three read since settle it, in the least comfortable way available.** A
name-level score would have marked `TestStaleRangeIDIsFencedOut` and
`TestBucketsAreIndependent` as opportunities, because their names describe
properties cleat genuinely has — and both are already tested, one of them three
times over. **The names were accurate and the conclusion drawn from them would
have been wrong.** A name tells you what a case is *about*; only reading tells you
whether the thing it is about is already covered on this side. That distinction
does not show up in any count.

That ratio is lower than `durabletask-go`'s, whose `backend_test.go` was 7–8 of
10. The absolute count is comparable or larger, and `cases` is a nominal
denominator — the same warning [next-upstream.md](next-upstream.md) already
carries for the DBOS figures.

## What I read, and what I only classified

**Read, assertions and all — two cases.** Everything else in this document is
classified from its name and its neighbours, which is exactly the method
ports#145 caught being wrong four times in twelve. **Treat every row below as a
hypothesis until someone reads it.** The two I read are marked `READ`.

## The one that already pays for the survey

`TestCreateWorkflowExecutionConcurrentCreate` — **READ**. It spawns concurrent
creates of one workflow id and asserts:

```go
s.Equal(int32(1), atomic.LoadInt32(&numOfErr))
```

Exactly one racer fails. Not "a create succeeded" — *exactly one loser*.

**cleat answers this differently, and nothing here asserts either answer.**
cleat's dedup returns the winner's run id to both callers rather than erroring
the loser, so the port would assert cleat's side of a real divergence. And
every existing dedup test in `ports/dbos-transact-py` starts **sequentially** —
`test_the_same_idempotency_key_starts_one_run`,
`test_a_completed_run_still_answers_for_its_idempotency_key`, and ports#156's
input/clock cases all send their second start after the first returns.

So *concurrent* dedup is unasserted in this repo, and it is the case where an
idempotency key is most likely to be wrong: two racing callers is the situation
the key exists for.

That is one case, found by reading two, and it is the kind
[next-upstream.md](next-upstream.md)'s criterion 3 asks for.

## Criterion by criterion

**1 — tests run without external infrastructure: FAILS.** Cadence's integration
suite runs under `docker compose` against **Cassandra**, in several profiles.
Not disqualifying, since this repo reads assertions and never runs them, but it
is why the persistence tests are written against a `TestBase` rather than a
fake, and some assertions are about the store's own bookkeeping.

**2 — it is a backend contract, which is cleat's shape: STRONGEST OF THE
CANDIDATES.** `common/persistence/persistence-tests/` is a dedicated contract
suite driven directly at the persistence layer — the same shape as
`durabletask-go`'s `backend_test.go`, at thirteen times the size. This is the
criterion that predicted durabletask-go's yield and Cadence is the only
remaining candidate that satisfies it: `conductor`'s core DAO tests are two
files, and `restatedev/sdk-typescript` is an SDK.

**3 — it probes cleat where open questions are: PARTIALLY.** The dedup,
run-id-reuse, state-close-status and continue-as-new cases sit exactly where
cleat's own surface is, and one of them found an unasserted gap on first
reading. Against that, a third of `executionManagerTest.go` is conflict
resolution for multi-cluster replication, which cleat has no analogue for at
any level.

**4 — it is a different model: WEAKEST, AND THIS IS THE REAL COST.** Cadence is
Temporal's ancestor and shares its vocabulary — task lists, transfer tasks,
mutable state, zombie executions. Choosing Cadence therefore **spends most of
the novelty a Temporal port would later bring**, while carrying assumptions
(sharding, replication, matching) that cleat has deliberately not adopted.

## What I would do with this

Not a recommendation to adopt or reject — that is a scoping document's job to
inform, not to make.

The cheapest useful next step is **not** a port. It is to take
`TestCreateWorkflowExecutionConcurrentCreate`'s property — *concurrent starts
under one idempotency key* — and add it to `ports/dbos-transact-py`, where the
fixture and harness already exist. That tests the gap this survey found without
paying for a fourth port directory, a harness, and a fixture set, which
[adding-a-port.md](adding-a-port.md) prices at a day with fixtures as the long
pole.

If the residue after that is still worth 20-odd cases, the port is worth
opening. If it is not, this document is the record of why.
