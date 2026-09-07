// Package main is the parent for the single-child await test.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleAwaitOneChild spawns one child and waits on it with AwaitChild -- the
// SINGULAR call, which is not AwaitAllChildren with a one-element list.
//
// The distinction is the reason this workflow exists. DBOS's single-child case
// is handle.get_result(), and the natural port of it was
// AwaitAllChildren([runID]) -- which is what test_a_single_child_round_trips
// does. So cleat's AwaitChild had no coverage at all, and cleat#845 lived there:
// a completing child wrote its result into the PARENT's await_child event and
// left the row's checksum stale, so the parent failed its next segment with a
// checksum mismatch and never resumed. The event type the injection matched,
// 'await_child', is written by this call and by no other.
//
// The child's sleep has to outlast the parent's first segment. A child that
// finishes sooner is taken by AwaitChild's "already completed" path, which
// records the result itself and never suspends -- so a fast child would pass
// against the defect and prove nothing.
func HandleAwaitOneChild(h cleat.HostCalls, ms int, tag string) (string, error) {
	runID, err := h.ChildWorkflow("child_leaf", fmt.Sprintf(`{"ms":%d,"tag":%q}`, ms, tag))
	if err != nil {
		return "", fmt.Errorf("spawn: %w", err)
	}

	result, err := h.AwaitChild(runID)
	if err != nil {
		return "", fmt.Errorf("await: %w", err)
	}

	return fmt.Sprintf(`{"runID":%q,"child":%s}`, runID, result), nil
}
