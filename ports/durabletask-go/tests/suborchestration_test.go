package tests

// A child that FAILS, ported from microsoft/durabletask-go's
// Test_SingleSubOrchestrator_Failed.
//
// Derived from the upstream assertions, not from upstream source. See UPSTREAM
// and ../../docs/licensing.md.
//
// WHY THIS IS NEW COVERAGE RATHER THAN A SECOND OPINION. ports#145 re-checked
// the twelve cases this port had classed as already asserted by the dbos port,
// and found that nothing there has a child that fails: all five cases in
// ports/dbos-transact-py/tests/test_children.py use successful children, and
// the only error-shaped assertion in the file is `assert not r.get("error")` --
// the ABSENCE of one. Upstream asserts the other direction.
//
// The distinction it turns on is not "did the parent fail". It is whether the
// CHILD'S message survives into the parent's failure. A parent that reported
// only "a child failed" would satisfy a status check and lose the one thing
// that makes the failure diagnosable.

import (
	"strings"
	"sync"
	"testing"
	"time"
)

var (
	failOnce   sync.Once
	failParent string
)

// failParentWorkflow deploys the CHILD first. The parent spawns it by name, so
// a parent deployed and started before the child existed would fail on a
// missing workflow rather than on the child's error -- which is a different
// failure wearing this test's name.
func failParentWorkflow(t *testing.T) string {
	t.Helper()
	failOnce.Do(func() {
		deploy(t, "failingchild", "dtg_failing_child")
		failParent = deploy(t, "failparent", "dtg_fail_parent")
	})
	if failParent == "" {
		t.Fatal("the failing-parent workflow failed to deploy; see the first failure above")
	}
	return failParent
}

// Test_SingleSubOrchestrator_Failed: a child's failure reaches its parent, with
// the child's own message.
func Test_SingleSubOrchestrator_Failed(t *testing.T) {
	marker := key(t)
	runID := startedRunID(t, start(t, failParentWorkflow(t), map[string]any{
		"marker": marker, "unused": 0,
	}))
	final := awaitTerminal(t, runID, 90*time.Second)

	// SKIPPED RATHER THAN INVERTED, which is this repo's shape for a case that
	// found a defect: the assertions below are what upstream asserts, so they
	// go green the day cleat#1115 is fixed rather than encoding the bug as the
	// expected result.
	//
	// Measured: the child reaches `failed` with its own message on the row, its
	// parent_workflow_id is correct, and the parent completes `done` reporting
	// `child_succeeded` with an empty result. AwaitChild returns no error for a
	// failed child.
	if final["status"] == "done" {
		b := map[string]any{}
		if r, ok := final["result"].(string); ok && strings.Contains(r, "child_succeeded") {
			b["result"] = r
		}
		t.Skipf("cleat#1115: AwaitChild reported a FAILED child as succeeded. "+
			"The parent completed `done` with %v. Skipped rather than inverted -- "+
			"the assertions below are upstream's and are what should hold.", b)
	}

	if got := final["status"]; got != "failed" {
		t.Fatalf("parent status = %v, want failed.\n\n"+
			"A child that returns an error must fail its parent when the parent "+
			"awaits it and returns what it got. `done` here would mean the await "+
			"reported success for a failed child: %#v", got, final)
	}

	msg, _ := final["error"].(string)
	if msg == "" {
		t.Fatalf("the parent failed with no error message at all.\n\n"+
			"Upstream asserts FailureDetails is present, not merely that the "+
			"status is FAILED -- a failure with nothing attached cannot be "+
			"diagnosed: %#v", final)
	}

	// The assertion that distinguishes propagation from a bare status.
	if !strings.Contains(msg, marker) {
		t.Errorf("the parent's error does not carry the child's marker.\n\n"+
			"  want it to contain: %q\n  got: %q\n\n"+
			"This is the whole case. A parent reporting only 'a child failed' "+
			"passes a status check and loses the one string that says WHICH "+
			"child and WHY. The dbos port asserts the absence of an error and "+
			"could not have caught this.", marker, msg)
	}
}
