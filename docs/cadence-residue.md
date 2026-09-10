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
