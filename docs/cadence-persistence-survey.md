# Cadence's persistence contract, case by case

Scoping `uber/cadence` as a third upstream, against the four criteria in
[next-upstream.md](next-upstream.md).

**Upstream:** https://github.com/uber/cadence
**Licence:** Apache-2.0, verified by API 2026-09-10. [licensing.md](licensing.md)
governs: this repo re-expresses assertions from prose and never copies.
**Pinned commit:** `c98e64e010409fbaae94cdc19c2e70ee662634b7`

## The headline

**129 test functions; roughly 20 to 27 are portable.** The rest is machinery
cleat does not have — multi-cluster replication, sharding, and task-list
matching — and that is a finding about cleat's shape rather than a gap in it.

| file | cases | portable | why the rest is not |
|---|---:|---:|---|
| `executionManagerTest.go` | 52 | ~15–20 | transfer tasks, zombie state, conflict resolution, replication |
| `historyTaskDLQPersistenceTest.go` | 7 | ~3 | ack-level bookkeeping is a Cadence-internal cursor |
| `historyV2PersistenceTest.go` | 5 | ~2–3 | history *branching* and forking; cleat's history is linear |
| `matchingPersistenceTest.go` | 12 | ~0–1 | task lists; cleat's workers poll `workflow_instances` directly |
| `queuePersistenceTest.go` | 4 | 0 | domain replication queues |
| `shardPersistenceTest.go` | 5 | 0 | cleat does not shard |
| **total** | **129** | **~20–27** | |

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
