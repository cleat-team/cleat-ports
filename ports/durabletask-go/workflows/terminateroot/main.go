// Package main spawns one child it waits for and one it does not.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleTerminateRoot reproduces upstream's Root: one sub-orchestration that
// has COMPLETED by the time the root closes, and one still RUNNING.
//
// Both children are spawned TERMINATE, which is cleat's spelling of upstream's
// `WithRecursiveTerminate(true)` -- the difference being that cleat fixes the
// policy per child at spawn time rather than passing a flag at terminate time.
//
// The root closes on its own rather than being terminated: cleat has no
// terminate route, and `enforceParentClosePolicy` fires when the parent CLOSES.
// So the assertion reached is the same predicate by the path this engine has.
//
// ORDER MATTERS. The long child is started FIRST, so that awaiting the short
// one cannot be what keeps the root alive -- upstream's L1 is completed and is
// explicitly not the thing the root is waiting on. Start them the other way and
// the root's own await would be the only reason the long child is still
// running, which is a different claim.
func HandleTerminateRoot(h cleat.HostCalls, marker string, shortMs int, longMs int) (string, error) {
	running, err := h.ChildWorkflowWithOptions("dtg_terminate_leaf",
		fmt.Sprintf(`{"tag":%q,"sleepMs":%d}`, marker+"-running", longMs),
		cleat.ChildWorkflowOptions{ParentClosePolicy: cleat.ParentClosePolicyTerminate})
	if err != nil {
		return "", fmt.Errorf("spawning the long-lived child: %w", err)
	}

	done, err := h.ChildWorkflowWithOptions("dtg_terminate_leaf",
		fmt.Sprintf(`{"tag":%q,"sleepMs":%d}`, marker+"-completed", shortMs),
		cleat.ChildWorkflowOptions{ParentClosePolicy: cleat.ParentClosePolicyTerminate})
	if err != nil {
		return "", fmt.Errorf("spawning the short-lived child: %w", err)
	}

	if _, err := h.AwaitChild(done); err != nil {
		return "", fmt.Errorf("awaiting the short-lived child: %w", err)
	}

	// Returning here closes the root while `running` is still sleeping.
	return fmt.Sprintf(`{"completedChild":%q,"runningChild":%q}`, done, running), nil
}
