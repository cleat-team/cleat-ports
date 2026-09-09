## 27. Repeated reclaim is counted but never bounded — dead-lettering is decided on a different axis

**Class:** Design difference
**Upstream test:** `test_failures.py::test_recovery_attempts`
**Status:** Won't fix — the counter shipped, the bound was declined (cleat-team/cleat#1008, cleat-team/cleat#1055, 2026-09-08)

**What upstream asserts**

DBOS increments `recovery_attempts` each time a workflow is re-dispatched after
losing its executor, and dead-letters it once that count passes a maximum. The
bound is on the **workflow**: however a run keeps failing to survive, there is a
point past which the system stops re-dispatching it.

**What cleat does**

cleat dead-letters on the **call-retry** axis instead. `deadLettered =
eligibleForDLQ && endedOnAnExhaustedCall(history)` — a durable call ran out of
its retry budget, which is a property of a *step*. A workflow that never reaches
a terminal failure at all is not covered by it.

`ReapStaleInstances` reclaims on `heartbeat_at < now() - interval` and consults
no counter. Nothing in `engine/` compares any column against a reclaim limit, so
a workflow whose worker dies mid-segment without recording a terminal failure is
reclaimed, runs again, and can lose its worker again indefinitely.

Since cleat-team/cleat#1055 the *count* exists — `workflow_instances.reclaim_count`,
incremented only by the reaper and returned on the API's workflow object — so
the loop is now visible. Nothing acts on it.

**Assessment**

Deliberate, and the reasoning is worth having here because "we have no bound" is
the answer that sounds like a gap.

The poison-pill case the bound exists to catch is closed by the worker's own
defaults. `--wasm-instance-timeout` (30s), `--wasm-wall-clock-ceiling` (5m) and
`--wasm-memory-max-mb` (32) are all on by default and interrupt a guest that
loops, blocks or allocates; epoch interruption is always enabled on the shared
engine. An interrupted guest produces a terminal workflow **failure**, not a
worker death, so it never reaches the reclaim path at all.

What remains reaching that path is the worker *process* dying for reasons
outside guest execution: host OOM under concurrency, node failure, deploy,
SIGKILL. Every one of those is infrastructure rather than workload. A threshold
that dead-lettered past N reclaims would convert *a node being redeployed* into
*permanent failure* of a workflow that did nothing wrong and that no human can
fix by looking at it — which is a worse failure than the one it prevents, given
what actually produces the input.

So cleat records the count and refuses to act on it, and the two systems differ
on what the bound is *for* rather than on whether recovery is bounded at all:
DBOS bounds attempts of a workflow, cleat bounds attempts of a call.

**Not portable, and not a skip either.** A skipped test implies an assertion
that should exist and does not. There is no cleat behaviour for
`test_recovery_attempts` to assert, by decision. The cleat-side property that
*is* asserted — that the count records reclaims and only reclaims, so an
operator can see a loop — is pinned upstream by
`engine/reclaim_count_records_reclaims_only_test.go` and
`engine/generation_is_not_a_reclaim_count_test.go`.

**Revisit if** a workflow is ever observed looping through reclaim for a reason
that is *not* infrastructure. `reclaim_count` is the thing that would show it;
before cleat#1055 there was no way to notice, since `generation` counts ordinary
claims too and a healthy workflow has been measured at 12.
