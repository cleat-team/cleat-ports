// Package main is the parent half of the childworkflow-continueasnew port.
//
// The question this exists to ask has no DBOS analogue, which is why the first
// port could not have covered it: a child that continues-as-new gets a NEW RUN
// ID, and the parent is holding the old one. Whether AwaitChild still resolves
// -- and whether it resolves to the FINAL iteration's result rather than the
// first one's -- is the whole subject of the upstream sample.
//
// Temporal's answer is that the parent sees one logical child across the chain.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCasnParent spawns a child that will continue-as-new `iterations` times
// and waits for it.
//
// The child's first run id is published as query state before the await, so a
// test can see which run the parent is holding even if the await never
// resolves -- which is the failure mode under test.
func HandleCasnParent(h cleat.HostCalls, key string, iterations int) (string, error) {
	runID, err := h.ChildWorkflow("sg_casn_child",
		fmt.Sprintf(`{"key":%q,"iterations":%d}`, key, iterations))
	if err != nil {
		return "", fmt.Errorf("spawn: %w", err)
	}
	h.SetQueryState("child", runID)
	h.SetQueryState("phase", "awaiting")

	result, err := h.AwaitChild(runID)
	if err != nil {
		return "", fmt.Errorf("await: %w", err)
	}
	h.SetQueryState("phase", "done")

	return fmt.Sprintf(`{"key":%q,"firstChild":%q,"childResult":%s}`, key, runID, result), nil
}
