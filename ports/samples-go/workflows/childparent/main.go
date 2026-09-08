// Package main is the parent half of the samples-go child-workflow port.
//
// Temporal's ParentClosePolicy is the concept this exists for. It is the part
// of the child-workflow model with no DBOS analogue, so the first port could
// not have covered it: DBOS children are independent runs, and "what happens
// to a running child when its parent goes away" is not a question that suite
// asks.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleChildParent starts one child under a named close policy and then stays
// alive for parentMs so the test can close it while the child is still running.
//
// The child's run id is published as query state rather than returned. It has
// to be readable from OUTSIDE while the parent is suspended, and in every
// interesting case here the parent never returns anything at all -- it is
// terminated on purpose.
//
// policy is passed through as a bare string rather than a typed constant so
// the port can send a value the SDK's own enum cannot express. That is
// deliberate: see TestAnUnrecognisedPolicyIsTreatedAsAbandon.
func HandleChildParent(h cleat.HostCalls, key string, policy string, childMs int, parentMs int) (string, error) {
	runID, err := h.ChildWorkflowWithOptions("sg_child_sleeper",
		fmt.Sprintf(`{"key":%q,"ms":%d}`, key, childMs),
		cleat.ChildWorkflowOptions{ParentClosePolicy: cleat.ParentClosePolicy(policy)})
	if err != nil {
		return "", fmt.Errorf("starting the child: %w", err)
	}

	h.SetQueryState("child", runID)

	// Published before the sleep, so a test that reads it is guaranteed the
	// child was started -- not merely that the parent got as far as running.
	h.SetQueryState("phase", "child_started")

	if parentMs > 0 {
		h.DurableSleepMs(int64(parentMs))
	}
	h.SetQueryState("phase", "parent_finished")
	return fmt.Sprintf(`{"child":%q}`, runID), nil
}
