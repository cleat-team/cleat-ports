package tests

// A child that had already completed is not terminated with its parent.
//
// Ported from microsoft/durabletask-go's
// Test_TerminateOrchestration_Recursive_TerminateCompletedSubOrchestration.
// Derived from the upstream assertions, not from upstream source.
//
// WHAT UPSTREAM ASSERTS. Root has two sub-orchestrations: L1, which it waits
// for and which COMPLETES, and L2, which it does not wait for and which is
// still RUNNING. Terminating Root recursively leaves L1 `COMPLETED` and makes
// L2 `TERMINATED`. Upstream's own comment is explicit: "In recursive case, L1
// orchestration is not terminated because it was already completed".
//
// WHY IT IS WORTH PORTING EVEN THOUGH CLEAT AGREES. cleat's
// enforceParentClosePolicy carries `AND status NOT IN ('done', 'failed')` on
// every arm and every dialect -- engine/store_lifecycle.go:554, :568,
// engine/mysql_lifecycle.go:1022 and neighbours. That predicate implements
// exactly upstream's rule and nothing tests it. A predicate that is never
// exercised is indistinguishable from one that was deleted.
//
// TWO MAPPINGS, both checked rather than assumed. Upstream decides recursion at
// TERMINATE time with WithRecursiveTerminate(recurse); cleat fixes it per child
// at SPAWN time via ParentClosePolicy, so `recurse=true` is a child spawned
// TERMINATE. And cleat has no terminate route -- the per-run verbs are
// allowed-signals, cancel, dag, disable, enable, history, promises, query,
// retry, routing, signal, start, tags, terminal, update -- so the policy is
// reached by letting the root CLOSE, which is when enforceParentClosePolicy
// runs.

import (
	"encoding/json"
	"sync"
	"testing"
	"time"
)

var (
	termOnce sync.Once
	termRoot string
)

func terminateRootWorkflow(t *testing.T) string {
	t.Helper()
	// The leaf first: the root spawns it by name, and a root deployed and
	// started before the leaf existed would fail on a missing workflow.
	termOnce.Do(func() {
		deploy(t, "terminateleaf", "dtg_terminate_leaf")
		termRoot = deploy(t, "terminateroot", "dtg_terminate_root")
	})
	if termRoot == "" {
		t.Fatal("the terminate-root workflow failed to deploy; see the first failure above")
	}
	return termRoot
}

func Test_TerminateOrchestration_Recursive_TerminateCompletedSubOrchestration(t *testing.T) {
	marker := key(t)
	runID := startedRunID(t, start(t, terminateRootWorkflow(t), map[string]any{
		"marker": marker, "shortMs": 500, "longMs": 60000,
	}))
	final := awaitTerminal(t, runID, 90*time.Second)
	if got := final["status"]; got != "done" {
		t.Fatalf("root status = %v, want done: %#v", got, final)
	}

	var body struct {
		CompletedChild string `json:"completedChild"`
		RunningChild   string `json:"runningChild"`
	}
	raw, _ := final["result"].(string)
	if err := json.Unmarshal([]byte(raw), &body); err != nil {
		t.Fatalf("root result is not the expected JSON: %v (%q)", err, raw)
	}
	if body.CompletedChild == "" || body.RunningChild == "" {
		t.Fatalf("root did not report both child ids: %q", raw)
	}

	// The completed child. Upstream's L1: finished before the root closed, and
	// the predicate excludes it.
	completed := awaitTerminal(t, body.CompletedChild, 60*time.Second)
	if got := completed["status"]; got != "done" {
		t.Errorf("the child that had already completed is now %v, want done.\n\n"+
			"enforceParentClosePolicy's TERMINATE arm carries "+
			"`AND status NOT IN ('done','failed')` precisely so a finished child "+
			"is not rewritten as failed when its parent closes. Upstream asserts "+
			"the same: a completed sub-orchestration is not terminated.", got)
	}

	// The running child. Upstream's L2: still going, and TERMINATE reaches it.
	running := awaitTerminal(t, body.RunningChild, 90*time.Second)
	if got := running["status"]; got != "failed" {
		t.Errorf("the child still running when its parent closed is %v, want failed.\n\n"+
			"It was spawned with ParentClosePolicy TERMINATE, which is cleat's "+
			"spelling of upstream's recursive terminate. `done` here would mean "+
			"the policy did not reach it -- and this assertion is what stops the "+
			"one above passing vacuously, since a policy that terminates NOTHING "+
			"also leaves the completed child alone.", got)
	}
	if msg, _ := running["error"].(string); msg == "" {
		t.Errorf("the terminated child carries no error message; the TERMINATE arm " +
			"sets error_msg = 'parent workflow terminated'")
	}
}
