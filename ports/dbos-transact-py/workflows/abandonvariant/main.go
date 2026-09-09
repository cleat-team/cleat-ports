// Package main is the ABANDON control for the entry-29 experiment.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleAbandonVariant spawns two children under REQUEST_CANCEL and
// awaits only the short one.
//
// TWO CHILDREN, because one cannot separate the questions. The parent cannot
// close until the child it awaits has finished, and the REQUEST_CANCEL arm of
// enforceParentClosePolicy carries `AND status NOT IN ('done','failed')`. So
// with a single awaited child, propagation is unobservable by construction: at
// the only moment the policy could fire, its only candidate has just left the
// eligible set. The long child is never awaited, so it is still running when
// the parent closes.
//
// THE LONG CHILD IS `cancellable`, NOT `child_leaf`, and that is what keeps
// this test inside the port's HTTP-only rule. `cancellation_requested` is a
// column no API exposes, so a test that wanted to see the flag would have to
// read the database -- which nothing in this suite does, and which would make
// the assertion dialect-specific into the bargain. `cancellable` polls
// PollCancellation and returns {"outcome":"cancelled"}, so the flag becomes a
// workflow RESULT and an ordinary GET can see it.
//
// The question underneath, from ISSUES entry 29: cleat's propagation fires
// from enforceParentClosePolicy, which runs when a parent CLOSES rather than
// when it is cancelled. So what does cancelling a parked parent actually do?
func HandleAbandonVariant(h cleat.HostCalls, shortMs int, longMs int, tag string) (string, error) {
	long, err := h.ChildWorkflowWithOptions("cancellable",
		fmt.Sprintf(`{"ms":%d,"poll":1}`, longMs),
		cleat.ChildWorkflowOptions{ParentClosePolicy: cleat.ParentClosePolicyAbandon})
	if err != nil {
		return "", fmt.Errorf("spawn long: %w", err)
	}
	short, err := h.ChildWorkflowWithOptions("child_leaf",
		fmt.Sprintf(`{"ms":%d,"tag":%q}`, shortMs, tag+"-short"),
		cleat.ChildWorkflowOptions{ParentClosePolicy: cleat.ParentClosePolicyRequestCancel})
	if err != nil {
		return "", fmt.Errorf("spawn short: %w", err)
	}

	result, err := h.AwaitChild(short)
	if err != nil {
		return fmt.Sprintf(`{"outcome":"await-error","long":%q,"short":%q,"error":%q}`,
			long, short, fmt.Sprintf("%v", err)), nil
	}
	return fmt.Sprintf(`{"outcome":"completed","long":%q,"short":%q,"result":%s}`,
		long, short, result), nil
}
