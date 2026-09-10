// Package main spawns one child, awaits it, and fails when the child does.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleFailParent spawns dtg_failing_child and returns whatever the await
// gives back.
//
// Upstream's Test_SingleSubOrchestrator_Failed asserts three things about the
// PARENT: its status is failed, its failure details are present, and their
// message contains the child's. So this parent must not swallow the error --
// returning it is the whole behaviour under test.
//
// The child is spawned by NAME rather than by a handle: cleat's
// ChildWorkflow(name, inputJSON) returns a run id, and there is no handle
// object to await. The assertion ports; the API shape does not.
func HandleFailParent(h cleat.HostCalls, marker string, unused int) (string, error) {
	childID, err := h.ChildWorkflow("dtg_failing_child",
		fmt.Sprintf(`{"marker":%q,"unused":0}`, marker))
	if err != nil {
		return "", fmt.Errorf("spawning the child: %w", err)
	}

	result, err := h.AwaitChild(childID)
	if err != nil {
		// The case under test. Wrapped rather than replaced so the child's own
		// message survives into the parent's failure -- which is exactly what
		// upstream asserts and what a parent that reported only "a child
		// failed" would lose.
		return "", fmt.Errorf("parent observed child failure: %w", err)
	}
	return fmt.Sprintf(`{"outcome":"child_succeeded","result":%q}`, result), nil
}
