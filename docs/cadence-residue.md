# Cadence: what the residue is once you read it

Follow-up to [cadence-persistence-survey.md](cadence-persistence-survey.md),
which estimated **~20–27 portable of 129** and said plainly that only two cases
had been read and *"treat every row below as a hypothesis until someone reads
it."* This is that reading, for `executionManagerTest.go` — the file carrying
most of the estimate (52 cases, ~15–20 claimed portable).

**Upstream:** uber/cadence, Apache-2.0, pinned `c98e64e0`. Assertions are
re-expressed from reading; nothing is copied. [licensing.md](licensing.md).

## Two automatic classifications, disagreeing, both wrong

| method | "portable" |
|---|---:|
| tests mentioning none of replication / shard / transfer-task / timer-task / task-list / zombie / reset **anywhere** | **3** of 52 |
| tests whose **assertions** mention none of them | **28** of 52 |

Neither is usable. The first is dominated by creation boilerplate — `TaskList`
appears in 42 tests because every workflow-creation helper sets the field, not
because the test is about task lists. The second passes `TestReplicationDLQ`,
`TestReplicationTasks` and `TestConflictResolveWorkflowExecutionWithCASMismatch`
as clean, because their assertions go through generic helpers.

### And the strictest bucket is a third wrong

The 3-test bucket — the most conservative reading available — contains
`TestDeleteCurrentWorkflow`, which carries this comment in the upstream source:

> `// "this test is only applicable for cassandra (uses TTL based deletes)"`

**One of the three is explicitly store-specific, said so by its own authors, and
neither scan could see it.** A prose comment is not a token either scan looks
for, and the test's assertions are entirely generic. So the ceiling on the
strictest classification is not 3, it is 2 — a third of the cleanest bucket was
wrong.

Measured across all three files: **4 of 64 tests carry an explicit skip or a
store-specific note** (`TestDeleteCurrentWorkflow`, `TestTransferTasksComplete`,
`TestCreateFailoverMarkerTasks`, `TestReadBranchByPagination`). That is a small
number and it is not the point — the point is which bucket the first one landed
in.

**Two readings that disagree by 9× and are wrong in opposite directions.** This
is the same trap as cleat#1137, where the narrow scan missed the confirmed bug
and the wide one flagged the fix as the defect. The conclusion is the same:
**no token scan settles this, and a number produced by one should not be
quoted.** The rows below were read.

## What reading three of the dedup family found

**`TestCreateWorkflowExecutionBrandNew` — portable, and it names a real gap.**
A second create of a running workflow id fails, and the *error carries the
winner's* start-request id, run id, `State`, and `CloseStatus`.

**cleat's equivalent carries neither state nor close status.** Measured on a
live worker:

```
first start                        -> {"id":"d1134808-…"}
re-start, winner still RUNNING     -> {"already_started":"true","workflow_id":"d1134808-…"}
re-start, winner status = "done"   -> {"already_started":"true","workflow_id":"d1134808-…"}
```

Byte-identical, HTTP 200 both times, with the run confirmed `done` in between.
So a caller retrying a start cannot tell whether it joined a live run or a
finished one, and the right next action differs — wait, or fetch the result.
It must make a second request to find out. Filed as cleat#1151.

**`TestCreateWorkflowExecutionRunIDReuseWithoutReplication` — NOT portable**,
and its own comment says why: *"this create should work since we are relying on
the business logic in history engine to check whether the existing running
workflow has finished."* It asserts that the **persistence layer is
deliberately permissive**, which is a statement about a layer boundary cleat
does not have. Porting it would assert a property of Cadence's internal
layering against cleat's public API.

**`TestCreateWorkflowExecutionDeDup` — needs more reading**; its assertions are
type-level (`IsType(&WorkflowExecutionAlreadyStartedError{})`) and the property
depends on setup this pass did not follow.

## Second pass: two more read, and one of them is a NON-gap

**`TestPersistenceStartWorkflow` — portable, but already captured.** Its
substance is the same property as `TestCreateWorkflowExecutionBrandNew`: the
already-started error carries `RunID`, `State`, `CloseStatus` and
`LastWriteVersion`. Filed as cleat#1151. The remainder of the case asserts
`ShardOwnershipLostError`, which cleat has no analogue for. **Counting this as a
second portable case would double-count one gap** — worth saying, because a
name-based pass would have counted it.

**`TestCreateWorkflowExecutionWithWorkflowRequestsDedup` — NOT a gap. cleat
already satisfies it, and arguably more idiomatically.**

Cadence distinguishes two duplicate conditions by error type:
`DuplicateRequestError` (this exact request was seen before, carrying its
`RequestType` and the `RunID` it produced) versus
`WorkflowExecutionAlreadyStartedError` (a different request tried to start an id
that is already running).

Measured on a live worker, cleat draws the same line with status codes:

| condition | cleat |
|---|---|
| same `Idempotency-Key` — your own retry | **200** `{"already_started":"true","workflow_id":…}` |
| same `Cleat-Concurrency-Key`, different request | **409** `workflow already running with key …` |

Those are the two situations that matter to a caller and they are already
separable: one means *your work is running*, the other means *someone else's is*.

The one dimension Cadence carries that cleat does not is `RequestType` — its
dedup covers request kinds beyond `start`. cleat's covers starts only, and the
signal half of that is already filed as cleat#1121 (a re-sent signal is a second
signal). So this case is fully accounted for with nothing left to port.

**Recording non-gaps matters as much as recording gaps.** A residue that only
ever grows is a residue nobody trusts, and "cleat already does this" is a result
the survey's row-by-name method could not produce.

## Third pass: `TestContinueAsNew` — not a gap, and I nearly filed it

The richest-looking case outside the dedup family. It asserts, on a
continue-as-new transition:

- the predecessor closes with a **distinct** `CloseStatusContinuedAsNew`;
- `FirstExecutionRunID` is carried **unchanged** onto the new run — a stable
  chain root readable from any link;
- the "current" pointer for the workflow id now names the new run.

Measured against cleat, a continue-as-new predecessor's record is:

```json
{"id": "0f749af4-…", "status": "done", "result": "{}", …}
```

`done`, with an empty result, and no field naming a successor or a root. On that
alone it reads as two gaps: no distinct close status, and no chain root.

**It is neither, and the port's own test is what says so.**

cleat carries a `continued_from` column and a separate
`GET /api/workflows/{id}/terminal` that walks the chain forward.
`test_the_chain_is_followable_to_the_run_carrying_the_result` records that this
was decided in cleat#826, and asserts **both** halves deliberately:

> polling the original id still reports done with an empty result, because that
> is what that row honestly contains … A change that made the first line return
> the successor's result would be the rejected option arriving by the back door,
> and would fail here.

So the predecessor's `done` is not an omission. `GetWorkflowByID` keeps meaning
"the row with this id"; making it follow the chain was considered and rejected,
because four call sites and the admin dashboard would have begun receiving a
different row, with a different id, than they asked for.

The one genuine difference that survives: Cadence's `FirstExecutionRunID` is a
**forward-stable root** readable from any link, where cleat's `continued_from`
is a **backward pointer**. Both reach the outcome; a root answers "every run of
this logical workflow" in one query where the backward chain needs a walk. That
is a design difference, not a defect, and proposing the root here would be
second-guessing a documented decision with no evidence of a problem behind it.

**The method note is the reusable part.** I had two gaps written down before
reading `test_continue_as_new.py`. What stopped me was checking **what the port
already asserts** rather than only what the engine's record shows. A missing
field in a response is evidence about that response, not about the system — and
in this repo the decision that made it missing is usually written down beside a
test that pins it. Read the port before concluding the engine lacks something.

## Sixteen read: where the file's residue actually is

Continuing case by case rather than by name. Every row below was read; none was
classified from its title.

| family | n | verdict |
|---|---:|---|
| dedup / lifecycle | 5 | **1 new issue** (cleat#1151), 1 duplicate of it, 1 non-gap, 2 not portable |
| `TestContinueAsNew` | 1 | **not a gap** — cleat#826 decided this shape deliberately |
| `TestWorkflowMutableState*` | 7 | **not portable** — CRUD round-trips on internal maps |
| corrupted / buffered / timer-tracking | 3 | **not portable** |

**Sixteen cases, one new issue.**

### The mutable-state family is one test written seven times

`Activities`, `Timers`, `ChildExecutions`, `RequestCancel`, `SignalInfo`,
`SignalRequested`, `Info`. All read; all the same shape — write an entry into
mutable state, read it back and assert `len == 1` and that it equals what was
written, delete it, assert `len == 0`.

That is a **persistence round-trip on Cadence's own bookkeeping maps**, not a
durable-execution contract. cleat exposes runs, statuses, results and history
events; it has no mutable-state blob with typed sub-maps for a port to assert
against.

One member carries something extra and it is worth separating out:
`ChildExecutions` also asserts a child records its `ParentWorkflowID`,
`ParentRunID` and `InitiatedID`. **The parentage half is already satisfied** —
`parent_workflow_id` is written on every child and, since cleat#1103, readable
from the API. Verified against the database: a child's API record carries it and
it matches. `InitiatedID` — the event id in the parent that initiated the child —
has no cleat analogue, and correlating a child back to a point in its parent's
history is a real capability cleat does not offer. Not filed: it is a plausible
want with no evidence anyone needs it, and this document is not a wish list.

### The last three

- **`TestCleanupCorruptedWorkflow`** — asserts a run marked `WorkflowStateCorrupted`
  stays readable and distinct from deleted, and that deleting the *current*
  pointer leaves the run loadable by run id. **Not portable twice over:** cleat
  has no corrupted state (grep finds only comments about data corruption), and
  no current/execution table split. The state exists to support Cadence's
  corruption-scanner tooling.
- **`TestUpdateAndClearBufferedEvents`** — `BufferedEventsCount` and
  `BufferedEventsSize`. No cleat analogue.
- **`TestWorkflowTimerTaskTracking`** — 62 lines and **three assertions, all
  `NoError`**. Nothing behavioural is asserted at all. Recorded because it is a
  reminder that upstream case counts include cases like this one, and a
  "portable" row costed from a name would have costed this at full price.

## The survey's table lists 6 of 14 test files, and does not say so

Counting `Test*` methods in every file the survey's table names: **85**. The
survey's headline is **129**. Its own rows sum to 85.

That is not an arithmetic error. `common/persistence/persistence-tests/` holds
**17 files, 14 of them test suites**, and the table names six. Counting the
other eight the same way gives 40, so 125.

**CORRECTION, and the 125 was mine.** I wrote that
`metadataPersistenceV2Test.go` "uses a receiver shape this count does not
match, which covers the rest" — a hedge where a re-measurement was owed. My
pattern assumed the receiver variable is `s` and typed the receiver
`[A-Za-z]+`, which excludes digits, so `*MetadataPersistenceSuiteV2` matched
**nothing** and a populated file read as **0**. Widening it gives that file
**7** and the directory **132**. Measured independently by another session
first, and reproduced here before being adopted.

So: **the six listed rows sum to 85, the published total is 129, the directory
holds 132.** The published total is neither its own sum nor the truth.
`132 − 129 = 3` is exactly `executionManagerTestForEventsV2.go`, the one file
whose name does not end `PersistenceTest.go` — consistent with a glob that
missed it, though the glob was not recorded, so that is the likeliest
reconstruction rather than an established one.

**The table is a selection presented as an enumeration.** That finding stands.

**The instrument defect is the part worth carrying.** `[A-Za-z]+` excluding a
digit is a mistake I had already made today — on `HistoryV2PersistenceSuite` —
and written down, and then made again hours later in a fresh script. Both
failures report a populated file as **empty**, which makes the corpus look
smaller and the survey look more complete. It is the direction that ends
enquiry.

Anyone reading the table concludes those six files are the corpus. They are not.

## And the omitted files include the family most likely to port

| file the table omits | cases |
|---|---:|
| `dbVisibilityPersistenceTest.go` | 12 |
| `domainAuditPersistenceTest.go` | 6 |
| `configStorePersistenceTest.go` | 5 |
| **`semaphoreMetadataPersistenceTest.go`** | **5** |
| **`semaphoreTasksPersistenceTest.go`** | **5** |
| **`semaphoreTokenPersistenceTest.go`** | **4** |
| `executionManagerTestForEventsV2.go` | 3 |

**Fourteen semaphore cases, none of them looked at.** cleat has a lock and
concurrency-key surface — `AcquireLock`/`ReleaseLock`, concurrency keys,
`tests/test_locks.py`, `test_distinct_keys_do_not_block_each_other` — so this is
the closest structural match in the whole directory, and it is the part the
survey's table does not mention.

Read to check rather than assumed. `TestGrantSameOwnerDifferentTokenIsRejected`:

> the owner claims the first token → `SemaphoreGrantApplied`
> a second grant of a **different** token to the **same owner** →
> `SemaphoreGrantAlreadyHeld`, **and the response reports the token the owner
> already holds**
> the second slot **was never claimed and is still free**

Two properties there, and cleat has a stake in both. The refusal **names what
you already hold** — the same shape as `already_started`, and the half cleat's
version does not do (cleat#1151). And a refused grant **must not consume
capacity**, which is a durability property a lock implementation can get wrong
silently.

Others in the family that look worth reading: `TestStaleRangeIDIsFencedOut`
(cleat has `ErrFenceLost` and generation fencing), `TestSeedIsIdempotent`, and
`TestBucketsAreIndependent`, whose cleat analogue already exists as a port test.

**Not claiming these are portable.** Names and one reading are not verdicts —
that is the whole method of this document, and six of the sixteen cases read so
far turned out not to be portable for reasons no name revealed. What is measured
is that **the family exists, matches a surface cleat has, and was outside the
table.**

## The six the table does list are now fully accounted for

| file | cases | verdict |
|---|---:|---|
| `executionManagerTest.go` | 52 | 18 read → **2 issues** (cleat#1151, cleat#1175) |
| `historyV2PersistenceTest.go` | 5 | **0** — history branch trees; cleat's history is linear |
| `historyTaskDLQPersistenceTest.go` | 7 | **0** — a DLQ of internal *history tasks* with ack cursors, not a workflow DLQ |
| `matchingPersistenceTest.go` | 12 | **0** — task lists, leases and ack levels; cleat's workers poll `workflow_instances` |
| `queuePersistenceTest.go` | 4 | **0** — domain replication queues |
| `shardPersistenceTest.go` | 5 | **0** — shard owner, `RangeID`, per-cluster ack levels |

The shard row needs its reason stated precisely, because cleat **does** have a
thing called a shard. `engine/sharded_store.go`'s `ShardConfig` is a connection
string and a tenant list — static routing. Cadence's shard is an owner with a
lease and a fencing `RangeID`, a coordination primitive for distributing work
across hosts. Same word, different concept; the survey's "cleat does not shard"
is right in substance and would read as wrong to anyone who greps first.

## Three semaphore cases read: one gap, two already covered

| case | verdict |
|---|---|
| `TestGrantSameOwnerDifferentTokenIsRejected` | **gap** — filed as cleat#1172 |
| `TestStaleRangeIDIsFencedOut` | **already covered** |
| `TestBucketsAreIndependent` | **already covered, twice** |

**The gap.** Their refusal reports the token the owner already holds and asserts
the refused grant did not consume the free slot. cleat's concurrency-key refusal
answers `409 {"error":"workflow already running with key K"}` — naming the key
the caller supplied, not the holder — and the holder cannot be looked up:
`?concurrency_key=` is ignored (nonsense returns the same rows as the real key)
and the listing is capped at 100 of 10,504 workflows.

**Already covered, and worth stating because a name-based pass would have
counted both as opportunities:**

- `TestStaleRangeIDIsFencedOut` asserts a superseded owner's writes fail with
  `ConditionFailedError`. cleat's analogue is generation fencing, already pinned
  by `test_workflow_management.py::test_a_stale_generation_is_refused_as_a_conflict`.
- `TestBucketsAreIndependent` asserts separate buckets keep separate counts.
  cleat has it **twice** — `test_locks.py::test_distinct_keys_do_not_block_each_other`
  and `test_cross_worker.py::test_distinct_keys_do_not_block_across_workers`.

**So the semaphore family is not a seam of untapped work**, and I called it "the
family most likely to port" an hour before reading any of it. One of three
produced a real issue — a better rate than `executionManagerTest.go` managed —
and two were already satisfied. That is the same distribution as everywhere else
here, which is why the estimate has never been revised: **the ratio does not
change, so a larger corpus does not imply a larger residue.**

Eleven of the fourteen semaphore cases remain unread.

## The honest read on the estimate

Five read now, and the verdicts do not cluster the way a count would suggest:

| case | verdict |
|---|---|
| `TestCreateWorkflowExecutionBrandNew` | portable — found cleat#1151 |
| `TestPersistenceStartWorkflow` | portable but **duplicates** #1151; rest is sharding |
| `TestCreateWorkflowExecutionWithWorkflowRequestsDedup` | **not a gap** — cleat already satisfies it |
| `TestCreateWorkflowExecutionRunIDReuseWithoutReplication` | not portable — asserts a layer boundary cleat lacks |
| `TestCreateWorkflowExecutionDeDup` | not portable — needs a caller-supplied run id |
| `TestContinueAsNew` | **not a gap** — cleat#826 decided this shape deliberately |

### Settling the fifth

`TestCreateWorkflowExecutionDeDup` was left undecided in the first pass because
its assertions are type-level. Read in full, the sequence is: create a run, drive
it to `Completed`, then create again with `CreateWorkflowModeWorkflowIDReuse`
and `PreviousRunID` set to **the same run id the request carries** — and expect
`WorkflowExecutionAlreadyStartedError`.

The property is a good one: **completion frees the workflow id, but a run id may
never be resurrected.** Reuse is a workflow-id-level permission, not a
run-id-level one.

**It is not portable, because its precondition does not exist in cleat.**
`handleStartWorkflow` accepts `input`, `entry_point`, `concurrency_key`,
`tenant_id`, `namespace` and `priority` — there is no run-id field. A caller
cannot name a run id, so it cannot reuse one, so the refusal has nothing to
refuse. This is the same shape as
`TestCreateWorkflowExecutionRunIDReuseWithoutReplication`: an assertion about a
control surface cleat does not expose.

Worth noting what that argument is *not*. It is not "cleat generates run ids so
the case is irrelevant" — a generated id could still be resurrected internally
after deletion, and that would be a real defect. It is specifically that **no
API path lets a test express the precondition**, which is a statement about
reachability from the port, not about the engine's correctness.

**One new issue from sixteen cases**, not five portable cases from five. That is
still **not** a basis for revising 20–27 to any other number — saying "so it is really 17" would be exactly the false precision this
document exists to avoid. What it does establish:

- **the portable cases cluster in dedup / current-execution / lifecycle**, not
  in the mutable-state families that dominate the count;
- **several "portable-looking" cases assert Cadence's internal layering**, which
  no name-based or token-based pass can detect;
- **the yield per case read is real** — one gap found per three read, and the
  survey's earlier two-case reading also found one (concurrent dedup, now
  ports#168).

## Recommendation, unchanged in shape from the survey

**Still do not open a fourth port directory.** Keep harvesting properties into
`ports/dbos-transact-py`, where the harness and fixtures exist, at roughly one
issue per three cases read. Open the port only if a reading pass finds a cluster
that needs Cadence-shaped fixtures to express — nothing so far does.


## Two more from `executionManagerTest.go`, and what the read count actually is

### `TestCreateWorkflowExecutionConcurrentCreate` — portable, and it found something

Two goroutines continue-as-new from the same base execution; exactly one must
fail. cleat **satisfies** this. Nothing in cleat tests it, and the reason it
holds is not the reason it appears to hold. Filed as **cleat#1175**.

`PostgresStore.ContinueAsNew` completes the predecessor under
`WHERE id = $1 AND assigned_to = $2 AND generation = $5`, and 0 rows rolls back
the successor insert too. Tracing which predicate excludes a second concurrent
caller:

| the second caller is… | excluded by |
|---|---|
| a different worker | `assigned_to = $2` — it never held the claim |
| a stale caller from an earlier claim | `generation = $5` — claiming bumps it |
| **a second caller on the same claim** | **`SET assigned_to = NULL`** |

Nothing in that statement bumps `generation`, so for the third row the `WHERE`
clause that reads as the guard cannot tell the two callers apart. The exclusion
is a **`SET` clause**. It works, it is unnamed, and no test would notice it
going away — which matters because **decision 4 of the capability-gap review,
already approved, is a durable record of which worker ran a workflow**, and the
cheapest implementation of that is to stop discarding `assigned_to`.

Measured, per function body rather than per file:

| | |
|---|---:|
| test funcs mentioning `ContinueAsNew` | 80 |
| test funcs using a concurrency construct | 125 |
| **both, in the same function** | **0** |
| both `ErrFenceLost` and a concurrency construct | **0** |

The first two rows are the controls. `ErrFenceLost` appears 57 times across 12
test files and **every** occurrence *arranges* the lost fence rather than racing
for it. That is the right way to test the predicate and it cannot see the
property Cadence asserts: not "a stale caller is rejected" but "two live callers
cannot both win."

### `TestUpdateWorkflowExecutionWithWorkflowRequestsDedup` — not a new issue, a constraint on an open one

Upstream keys dedup on **`(RequestID, RequestType)`**, not `RequestID`: one
client request id legitimately produces a `Start` row *and* a `Signal` row, and
re-presenting either is an error without shadowing the other.

cleat's `idempotency_keys` has no operation-type column. That is harmless today
only because signals carry no key at all (**cleat#1121**) — there is nothing for
a start's row to collide with. It stops being harmless the moment #1121 lands.
Recorded as a comment there rather than as a new issue, since it constrains that
implementation rather than describing a present defect.

### The read count, stated with its denominator

The row above now says **18 read**. A mechanical scan — every case name in
`executionManagerTest.go`, matched against this document — reports **22
accounted for, 30 unread**.

The two numbers measure different things and both are in the file, so neither is
a correction of the other. **18** is cases *adjudicated*: a verdict was reached
and written down. **22** is names that *appear* here, four of which appear only
in passing. Earlier in this survey I said "36 unread", which is neither; it was
`52 − 16` carried forward after the read count had moved.

**30 is a lower bound on what is unread**, and deliberately so: the scan counts
a name as read if it appears anywhere in this document, which can only
over-count reading. That is the direction that ends enquiry, so it is the one
to state explicitly rather than to round off.


## `TestGetCurrentWorkflow`, and a verdict this survey did not have a name for

Read in full. It has two halves and they land differently.

**Half one: the current-run pointer survives completion.** The test drives a run
to finish, then asserts `GetCurrentWorkflowRunID` still resolves the workflow id
to it. cleat's equivalent is the `continued_from` walk — `GetTerminalRun`, in
`engine/terminal_run.go` — which follows a chain forward to its live end. cleat
**has** the capability, so by the usual reckoning this is *already covered* and
the case produces nothing.

Checking it produced **cleat#1177**.

`PostgresStore.successorOfRun` issues

```go
s.db.QueryRowContext(ctx, `SELECT id FROM workflow_instances WHERE continued_from = $1`, id)
```

on a plain `*sql.DB`, outside any RLS transaction, against a table with RLS
**enabled and forced** and a fail-closed policy —
`USING (tenant_id = cleat.assert_tenant_set())`, a function that `RAISE`s when
the tenant is unset. The tenant is only ever set by `beginTxWithRLS`, via
`set_config(..., true)`, which is transaction-local. This statement never opens
one. The MySQL and MSSQL arms carry `AND tenant_id = ?` and never depended on
RLS; only the PostgreSQL arm omits it.

Measured against a scratch database with every migration applied, as a role with
neither `rolsuper` nor `rolbypassrls`:

| run | result |
|---|---|
| no transaction — what the code does | **`ERROR: cleat.tenant_id is not set`** |
| in a tx, owning tenant *(control)* | returns the successor |
| in a tx, another tenant *(control)* | 0 rows |

So on PostgreSQL, `GetTerminalRun` **errors whenever a chain has a successor**.
A peer settled the one thing I could not: `cleat_dispatcher`, the BYPASSRLS
role, is `NOLOGIN`, so this is a broken feature and not a cross-tenant read.

**Half two: a brand-new create is refused when the workflow id already has a
finished run.** Not portable, and for the reason already recorded against
`TestCreateWorkflowExecutionDeDup` — cleat has no caller-supplied workflow id.
`workflow_instances.id` is `gen_random_uuid()`. The nearest cleat concept is the
idempotency key, whose semantics are #1047/#1017/#1121/#1167.

### The verdict this survey did not have a name for

Every case so far has been *a gap*, *not a gap*, or *not portable*. This one is
none of them. cleat has the capability, has it deliberately, and has it
**broken** — and no verdict in the vocabulary covers "the feature is present and
does not work", because the survey was built to ask what cleat is missing.

**It is also the only verdict a name-level triage could never reach.** The name
`TestGetCurrentWorkflow` describes a property cleat genuinely has. Scored from
the name it is *already covered*, filed under nothing, and the defect keeps.
What found it was reading the case, asking which cleat function answers the same
question, and then reading that function — three steps past where a triage
stops.

This is the same argument recorded above for the two semaphore cases scored
*already covered*, and it now cuts the other way: **"cleat has this" is a claim
about the API, and the survey kept treating it as a claim about the behaviour.**

### `TestCreateWorkflowExecutionStateCloseStatus` — not portable

Asserts that `(state, closeStatus)` pairs are consistent at write time:
`Created`/`Running` with any terminal close status is rejected, and `Completed`
with `None` is rejected too. It guards a **two-field encoding supplied by the
caller**. cleat has one `status` column, written only by store methods —
migration 038 notes it is deliberately not even `CHECK`-constrained — so the
inconsistency this defends against has no way to be expressed. The `Update`
variant is the same shape.

### The remaining cases, triaged rather than read

Stated as triage so the count stays honest: the following were classified by the
**API surface their bodies exercise**, not by reading their assertions. Each is
assigned to a family this document has already adjudicated with a reason.

| family | cases | already-recorded reason |
|---|---:|---|
| transfer / timer / replication task queues | 9 | internal task queues with ack cursors; cleat's workers poll `workflow_instances` |
| CRUD round-trips on mutable state | 6 | same as the `TestWorkflowMutableState*` family |
| active-cluster selection policy | 2 | multi-cluster replication; cleat has no cluster-selection concept |

That is 17 assigned by surface, and **triage is not reading** — the semaphore
family is the standing evidence, where two cases whose names and surfaces both
looked like opportunities turned out to be satisfied twice over. These 17 remain
available to anyone who wants to check the family assignment by reading them.


## Auditing the *already covered* verdicts

The section above says the survey's blind spot is the **covered** bucket, so the
obvious next move was to audit it rather than leave the observation as a remark.
The question asked of each covered verdict: **is it backed by something that
executed, or by something that was read?**

| verdict | backed by | holds? |
|---|---|---|
| `TestCreateWorkflowExecutionWithWorkflowRequestsDedup` — cleat already satisfies it | a live-worker measurement: 200 `already_started` vs 409 on the concurrency key | **yes** |
| `TestStaleRangeIDIsFencedOut` | `test_a_stale_generation_is_refused_as_a_conflict` (exists, passes) | **yes** |
| `TestBucketsAreIndependent` | `test_distinct_keys_do_not_block_each_other` and its cross-worker sibling | **yes** |
| parent-close cascade — *"cleat already has a configurable cascade"* | four port test files driving all three of `ABANDON`, `TERMINATE`, `REQUEST_CANCEL`, including `ports/durabletask-go/tests/terminate_recursive_test.go` | **yes** |
| `TestContinueAsNew` — the chain is followable | `test_the_chain_is_followable_to_the_run_carrying_the_result` | **no — see below** |

Four of five are backed by something that ran. That is a better result than the
section above implied, and worth recording: the *covered* bucket is where this
class of defect lives, but it is not where most of them live.

### The fifth, and why a passing test was not enough

`test_the_chain_is_followable_to_the_run_carrying_the_result` starts a workflow
that continues as new, waits for the chain, calls
`GET /api/workflows/{id}/terminal`, and asserts the successor comes back. Real
chain, real PostgreSQL, in CI, **green** — and it was green over
**cleat#1177**, a statement that raises on every chain that has a successor.

`scripts/worker.sh` connects the worker as `postgres://postgres`. A superuser
bypasses RLS unconditionally, `FORCE ROW LEVEL SECURITY` included. Same
statement, same rows, same database, role changed:

```
postgres  (this harness)   -> returns the successor
cleat_app (deployments)    -> ERROR: cleat.tenant_id is not set
```

**The test is not weak and its assertions are not vacuous. It measures a system
configured so that the thing that breaks cannot break.** Filed as
cleat-ports#198, and the cleat-side census that bounds it as cleat#1178.

### What the audit changes about the method

"Backed by a passing test" is one question and **"backed by a passing test run
in the configuration that matters"** is another, and only the second is worth
anything. Privilege level is the part of a configuration nothing states: a
harness picks a convenient credential once, in a setup script, and every
mechanism that credential disables reports green from then on.

The concrete follow-up is in cleat-ports#198 as a **falsifiable prediction**
rather than a caveat: pointing the worker at `cleat_app` should turn red exactly
the tests reaching `/terminal`, because cleat#1178 enumerates the whole
population and finds one live statement. If anything else breaks, the census is
incomplete — which is the more valuable outcome and the reason to run it cheaply
instead of reasoning about it further.


## The `ConflictResolve` family — 8 cases, 1623 lines, not portable

The largest unadjudicated block left in `executionManagerTest.go`. Triaged by
the concepts each body exercises, not by name:

| case | lines |
|---|---:|
| `TestConflictResolveWorkflowExecutionCurrentIsSelf` | 507 |
| `TestConflictResolveWorkflowExecutionWithCASMismatch` | 165 |
| `…WithTransactionCurrentIsNotSelf` | 170 |
| `…WithTransactionCurrentIsNotSelfWithContinueAsNew` | 201 |
| `…WithTransactionCurrentIsSelf` | 119 |
| `…WithTransactionCurrentIsSelfWithContinueAsNew` | 148 |
| `…WithTransactionZombieIsSelf` | 142 |
| `…WithTransactionZombieIsSelfWithContinueAsNew` | 171 |

All eight turn on `VersionHistories` and `LastWriteVersion`; six also on
`ResetWorkflowSnapshot` + `CurrentWorkflowMutation`. These are Cadence's
**cross-cluster replication** primitives — the family resolves a conflict
between two clusters' versions of the same workflow, deciding which run becomes
current and what becomes of the loser.

Counting non-test files in cleat that mention each concept:

| concept | files in cleat |
|---|---:|
| `version_history` | **0** |
| `last_write_version` | **0** |
| `cluster_name` | **0** |
| `active_cluster` | **0** |

cleat is single-cluster: there is no second version of a workflow to conflict
with, so the question the family asks cannot be posed. **Not portable**, for one
reason covering all eight.

### The homonym, which is the reusable part

`zombie` returns **3** non-test files in cleat. Under a name-level triage that
reads as a hit, and it is the signal that would promote the two `ZombieIsSelf`
cases to portable.

It is a different concept wearing the same word. Cadence's `WorkflowStateZombie`
is a run that **exists but is not current** for its workflow id — a lifecycle
state produced by replication and reset. cleat's zombie is a **process still
running after it should have stopped**: `setup.go`'s *"background zombie reaper
goroutine"*, `store_intent.go`'s *"a zombie that keeps running after this
returns"*. A row's status versus an escaped goroutine. Nothing transfers.

That is the **third** distinct way a name has misled this survey:

| | |
|---|---|
| the two semaphore cases | names described properties cleat genuinely has → would have been scored **opportunities**, were already satisfied |
| `TestGetCurrentWorkflow` | name described a property cleat has **and does not deliver** → scored covered, hid cleat#1177 |
| `ZombieIsSelf` ×2 | name matches a cleat term meaning something else → a **false synonym** |

A false negative, a false positive, and a false friend. The rule is unchanged and
has now earned its third independent confirmation: read the body, then read
cleat's implementation of whatever the body turns out to be about.

`store_admin_rereplay.go` is the nearest thing cleat has to a reset, and makes
the point a fourth time: it returns a stopped workflow to `ready` and replays its
recorded history **in place**, preserving every step already taken. Cadence's
reset builds a **new run** from a snapshot and re-points the current pointer at
it. Same word, different operation.
