// Package main is the workflow the post-cancellation case runs against.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCancelChild waits until it observes cancellation, then starts a child
// and reports what happened.
//
// UPSTREAM ASSERTS THE OPPOSITE OUTCOME, which is the point of the case.
// temporalio/sdk-go's TestCantStartChildAfterBeingCancelled asserts the child
// is never started and the run ends with a CanceledError. cleat's cancellation
// is cooperative -- the guest polls and decides -- so it permits the child, and
// the run ends `done`.
//
// The child is started AFTER the observation on purpose. "A workflow may ignore
// cancellation" is already asserted by
// ports/dbos-transact-py/tests/test_cancellation.py; what is not asserted
// anywhere is that a cancelled workflow may still commit a NEW DURABLE SIDE
// EFFECT. Continuing to run and spawning a child are different claims, and only
// the second is interesting once the first is known.
//
// The wait is 400ms and not a bare integer: `AwaitSignals` takes a
// time.Duration, and cleat#1331 makes anything under 1ms a livelock rather than
// an error.
func HandleCancelChild(h cleat.HostCalls, childDef string, slices int) (string, error) {
	observed := false
	reason := ""
	for i := 0; i < slices; i++ {
		if c, r := h.PollCancellation(); c {
			observed, reason = true, r
			break
		}
		h.AwaitSignals([]string{"never"}, 400*time.Millisecond)
	}
	if !observed {
		// Reported rather than returned as an error: the test needs to tell
		// "cleat refused the child" from "the cancel never arrived", and those
		// are different failures with different causes.
		return `{"outcome":"never-observed-cancellation"}`, nil
	}

	childID, err := h.ChildWorkflow(childDef, `{"marker":"post-cancel","n":0}`)
	if err != nil {
		return fmt.Sprintf(`{"outcome":"child-refused","reason":%q,"err":"%v"}`, reason, err), nil
	}
	return fmt.Sprintf(`{"outcome":"child-started","reason":%q,"childId":%q}`, reason, childID), nil
}
