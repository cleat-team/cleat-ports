# `temporalio/sdk-go` — the cancellation cases, read against four ports

The third cluster read from this upstream, after
[schedules](temporalio-sdk-go-schedules-survey.md) and
[updates](temporalio-sdk-go-updates-survey.md).

Read at `902937accd7ac67cd8ed16e73b1db2b75cab48a7` (2026-09-12). Fifteen cases,
selected by the subject bucketing in [`next-upstream.md`](next-upstream.md).

**This is the first survey here that does the cross-port check first**, which
[`next-upstream.md`](next-upstream.md) identifies as the step every previous
estimate skipped: a case is not worth porting because cleat has the surface, it
is worth porting because **no port already asserts the property** — and the four
ports come from four upstreams with four vocabularies, so no mechanical check
finds the overlap.

## What the existing ports already assert about cancellation

Fourteen files match `grep -rli cancel ports/*/tests/`. The ones that assert
rather than mention:

| file | asserts |
|---|---|
| `dbos-transact-py/tests/test_cancellation.py` | a polling workflow observes cancellation; a cancelled workflow still reports `done`; **cancellation is cooperative and a workflow may ignore it**; cancel stops a workflow that does not cooperate |
| `dbos-transact-py/tests/test_cancel_propagation.py` | cancelling a parked parent does not stop it; a request-cancel child observes it; an abandon child is not reached |
| `dbos-transact-py/tests/test_bulk_cancel.py` | cancelling several stops all of them; cancelling one leaves the others running |
| `samples-go/tests/child_workflow_test.go` | abandon outlives its parent; terminate child stops with the parent; request-cancel child is asked to stop; the three legal policies; a mis-cased policy is refused |
| `samples-go/tests/terminal_statuses_test.go` | the terminal set is the engine's — `done`, `failed`, `terminated`, `dead_lettered`, and **no `cancelled`** |

That last row decides several verdicts on its own: **cleat has no `cancelled`
terminal status**, so every upstream case whose assertion is
`errors.As(err, &canceledErr)` is asserting a status cleat does not have.

## The verdicts

| # | case | verdict |
|---|---|---|
| 1 | `TestCancellation` | covered — `test_cancel_stops_a_workflow_that_does_not_cooperate` |
| 2 | `TestAdvancedPostCancellation` | covered — post-cancel work then a clean finish is `test_cancellation_is_cooperative_and_a_workflow_may_ignore_it` |
| 3 | `TestWaitForCancelWithDisconnectedContext` | covered — same property, smaller case |
| 4 | `TestCancelMultipleCommandsOverMultipleTasks` | covered — same property again |
| 5 | `TestCascadingCancellation` | covered — `TestARequestCancelChildIsAskedToStop` |
| 6 | `TestCancelChildWorkflowAndParentWorkflow` | covered — `test_a_live_request_cancel_child_observes_the_cancellation` |
| 7 | `TestAdvancedPostCancellationChildWithDone` | covered — combination of 2 and 5 |
| 8 | **`TestCancellationWithOptions`** | **gap → filed, not ported** — cleat#1351 |
| 9 | `TestCantStartChildAfterBeingCancelled` | **gap, portable** — see below |
| 10 | `TestCancelChildWorkflowUnusualTransitions` | not portable — needs `QueryWorkflow` to learn the child id; cleat has `SetQueryState` only |
| 11 | `TestCancelTimerAfterActivity` | not portable — cancels a timer *handle* inside the workflow; cleat has no cancellable timer |
| 12 | `TestCancelTimerViaDeferAfterWFTFailure` | not portable — needs worker options making a panic fail the task |
| 13 | `TestCancelChildAndExecuteActivityRace` | not portable — activities, and its only assertion is `NoError` |
| 14 | `TestReturnCancelError` | not portable — activity cancel-error taxonomy |
| 15 | `TestMultipleUpdateOrderingCancel` | not portable — update ordering with in-workflow cancellation |

**7 covered elsewhere, 1 gap filed, 1 gap portable, 6 not portable.**

### The number this cluster is really about

Seven of fifteen were already asserted, by **two different ports from two
different upstreams**, and not one of them names a `temporalio` case. A
name-based duplication check reports **zero** overlap here. That is the
prediction in `next-upstream.md` confirmed on the first cluster it was applied
to, and it is why the 30–40 estimate for this file was an upper bound.

## The one finding: cleat#1351

`TestCancellationWithOptions` cancels with a reason and asserts the reason is in
the workflow's history. cleat stores it — `RequestCancellation` writes
`cancellation_reason` on all three dialects — delivers it to the guest through
`PollCancellation()`, and returns it from **no API route**. Measured against six
read paths; `cancellation_requested` is absent from all of them too, so a
cancelled run reports `status: "ready"` and nothing else.

It matters here more than it would elsewhere precisely because of the row above
that says cancellation is **cooperative**: "cancelled but still running" is a
normal and possibly permanent state in cleat, and it is the one state no read
path can show.

**Not ported**, for the reason the schedules survey gave for deferring
`TestSchedulePause`: a test written today would assert today's answer and be
rewritten by the fix.

## The one portable gap: no new work after cancellation

`TestCantStartChildAfterBeingCancelled` asserts that a workflow which observes
cancellation and then tries to start a child does not get one. cleat has the
analogous machinery — `stopBeforeNewWork()` gates fresh awaits and updates in a
segment that has decided to end (`engine/signaller.go`, `engine/updater.go`) —
and **no port asserts it**: the existing cancellation tests all stop at "the
workflow observed the request".

It needs one workflow package: poll cancellation, then attempt a
`ChildWorkflow` call, and report what came back. That is the natural next port
from this cluster and the only one in it.

## Method note

The cross-port check took about ten minutes: `grep -rli cancel ports/*/tests/`
for the file list, then reading the test *names* — which in this repo are
sentences, so the names alone settled six of the seven "covered" verdicts
without opening a body. Doing it before reading the upstream cases would have
saved most of the reading; doing it at all is what turned an estimated cluster
of fifteen into two cases worth acting on.
