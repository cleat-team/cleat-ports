# durabletask-go — findings

Divergences between cleat and `microsoft/durabletask-go` found while porting.
Entries are numbered and never renumbered; `scripts/check-issue-numbers.sh`
rejects holes and duplicates.

## 1. An operator cannot suspend a running workflow, and events cannot buffer against one

**Class:** Missing capability

Upstream's `Test_SuspendResumeOrchestration` suspends a running orchestration,
raises events at it that must **buffer unconsumed**, asserts the status is
`SUSPENDED` and that the orchestration has not completed, then resumes and
asserts the buffered events are delivered in order.

cleat has no operator suspend. Verified first-hand rather than from the survey:

```sh
# none of the 52 host exports
grep -oE '\.Export\("[^"]+"\)' engine/imports.go | sed 's/.*Export("//;s/")//' \
  | grep -iE 'suspend|resume|pause'

# and no route: the per-run verbs are
#   allowed-signals cancel dag disable enable history promises query
#   retry routing signal start tags terminal update
grep -c 'suspend\|resume' cmd/cleat-worker/server.go     # 0
```

**cleat does suspend, and that is the distinction worth stating.** A workflow
suspends whenever it awaits — a durable sleep, a signal await, a child await —
and resumes when the wake condition is met. That is **engine-driven**: the
workflow decides, the operator cannot. Upstream's is **operator-driven**: an
external actor freezes a run that did not ask to be frozen.

Conflating the two would make this look already-covered. It is not: no caller
outside the workflow can put a run into that state or take it out.

**The nearest thing cleat has is `cancel`, and it is not a substitute** — it is
terminal by design (ISSUES 21 in the dbos port settles that cancellation is
cooperative and one-way). Suspend's whole point is that it is reversible.

**What the port cannot assert without it**, and why this is filed rather than
worked around: the event-buffering half. "Events raised at a suspended run are
held and delivered on resume" has no expressible form when nothing can be
suspended, and a test that signalled a *running* workflow instead would be
asserting ordinary delivery — which `ports/dbos-transact-py/tests/test_signals.py`
already covers, under a name claiming something it did not test.
