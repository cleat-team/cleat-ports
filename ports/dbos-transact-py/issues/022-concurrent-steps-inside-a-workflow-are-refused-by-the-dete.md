## 22. Concurrent steps inside a workflow are refused by the determinism analyzer

**Class:** Deliberate difference
**Upstream test:** `tests/test_concurrency.py` — 9 of 11 cases, headed by
`test_high_async_concurrency`, `test_gather_manysteps`,
`test_gather_distinct_steps_deterministic_order`
**Status:** Closed — unportable in principle, not pending a fix

**Count first, because the inventory is wrong about this file too.** The README
listed 21 cases. Counted by collection at the pin it is **11**; the 21 is the
`grep '^def test_'` figure, the same inflation corrected for `test_queue.py` in
#20. Re-derive with `scripts/count-queue-cases.py`.

**What upstream asserts**

Nine of the eleven are `async def`, most using `asyncio.gather`. They exercise
the Python SDK's async model — several steps of **one** workflow running
concurrently, streams written from concurrent tasks, event set/get under load,
and thread starvation during recovery:

    test_gather_manythings                                 events, streams
    test_gather_manysteps
    test_gather_many_send_async
    test_gather_many_write_stream
    test_gather_many_write_stream_from_step                streams
    test_gather_many_set_event                             events
    test_high_async_concurrency                            asyncio.gather
    test_async_recovery_direct_child_no_thread_starvation  asyncio.gather, recovery
    test_gather_distinct_steps_deterministic_order         asyncio.gather

The remaining two (`test_concurrent_workflows`, `test_concurrent_getevent`) are
synchronous and use threads to drive **separate** workflows. Those look
portable — starting N workflows and asserting all complete is something cleat
does — and are the work-list for this file.

**What cleat does: refuses the constructs at build time.**

Not "does not support" — the analyzer rejects the whole family, syntactically
and before anything runs (`internal/closure/closure.go`):

| code | construct | site |
|---|---|---|
| **E001** | `go` statement | `:275` |
| **E002** | channel send | `:288`, `:308` |
| **E012** | `close()` | `:386` |
| **E013** | `sync.{Mutex, RWMutex, WaitGroup, Once, Cond, Pool, Map}` | `:412` |
| **E013** | calls on a sync-typed variable, e.g. `mu.Lock()` | `:441` |

That last row matters: the ban catches `mu.Lock()` where `mu` is a
`sync.Mutex` variable, not merely the written-out selector, so it is not
evadable by ordinary indirection.

**Assessment**

A DBOS workflow may `asyncio.gather` its steps. **A cleat workflow may not run
anything concurrently at all, by design.** E001's own message states the reason:

> goroutines introduce non-deterministic scheduling across replays

So these cases are not unportable because a control is missing. They are
unportable because **no implementation that preserves replay determinism could
pass them.** That distinction is the whole entry: "cleat lacks a control"
invites someone to add the control, and here there is nothing to add.

Already pinned by `ports/samples-go/tests/nondeterminism_test.go`
(`TestForbiddenConstructsAreRefusedAtBuildTime`), the port of upstream
`goroutine/` and `mutex/`, which records the same refusal from the other
direction.

**Note the near-miss, because it is the useful part.**

This file was first assessed against #20's criterion — `ConcurrencyKey` is a
mutex not a semaphore, so bounded parallelism is unrepresentable. That criterion
is **correct and is the wrong instrument here**: it would have bucketed all nine
async cases as "needs a control cleat lacks", which is true of the queue file
and false of this one.

The conclusion would have been right — the cases are unportable — with the
reason wrong. **Nothing downstream would have contradicted it**, because the
tests really do fail and the entry really would have explained why. A correct
conclusion with a wrong reason survives every check that only looks at the
conclusion.

What caught it was counting the cases and reading what they exercise, rather
than applying the criterion that had just worked on the neighbouring file.

**Method:** the cleat column is read from `internal/closure/closure.go` with line
numbers, verified independently by a second session. The upstream column is
collected and characterised by AST from the pinned commit — names and constructs,
**not bodies** — so the 2-portable / 9-unportable split is directional rather
than exact.

`tests/test_async.py` has since been read case by case (WORKLIST.md) and this
covers **5 of its 33** cases, not "much of" it: the four `asyncio_wait` cases and
`test_concurrent_patch_async`, all of which drive several step coroutines of one
workflow concurrently. The estimate written here was 57 by an old grep-based
count and was made without reading the file; the collected figure is 33.
