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
It must make a second request to find out. Filed as cleat#1149.

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

## The honest read on the estimate

One of three read is portable; one is definitely not; one is undecided. That is
a sample of three, and it is **not** a basis for revising 20–27 to any other
number — saying "so it is really 17" would be exactly the false precision this
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
