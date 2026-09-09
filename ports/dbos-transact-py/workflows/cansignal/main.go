// Package main is the workflow under test for a signal at a continue-as-new
// boundary.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCanSignal awaits "go" in its first iteration, continues as new, then
// awaits "carried" in its second.
//
// THE SHAPE IS THE ASSERTION. The test delivers "carried" BEFORE "go", so by
// the time the first iteration continues as new there is an
// already-delivered, never-consumed signal sitting on the run. The second
// iteration then asks for it.
//
// Upstream's `Test_ContinueAsNew_Events` carries such events across the
// boundary, behind an explicit `task.WithKeepUnprocessedEvents()`. cleat has no
// counterpart, and the storage says why: `workflow_signals` is keyed
// `(workflow_id, signal_name)` and `ContinueAsNew` mints a NEW run id without
// touching that table -- zero mentions of `workflow_signals` inside the
// function, on all three dialects.
//
// So the expected outcome is `timedout`, and this workflow exists to make that
// observable rather than inferred. The timeout is a parameter so the test can
// keep it short: the assertion is that nothing arrives, and a longer wait only
// makes the suite slower without making the claim stronger.
//
// `announce` marks the second iteration having STARTED, separately from what
// it concludes. Without it, a chain that never reached its second iteration
// and a second iteration that timed out both look like "no signal was seen".
func HandleCanSignal(h cleat.HostCalls, key string, timeoutMs int, second int) (string, error) {
	if second != 0 {
		if _, err := h.DurableCall("flaky", "op",
			fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-second")); err != nil {
			return "", fmt.Errorf("announce second: %w", err)
		}
		name, payload, timedOut, err := h.DurableAwaitSignals([]string{"carried"}, int64(timeoutMs))
		if err != nil {
			return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
		}
		if timedOut {
			return `{"outcome":"timedout","iteration":2}`, nil
		}
		return fmt.Sprintf(`{"outcome":"carried","name":%q,"payload":%q,"iteration":2}`,
			name, payload), nil
	}

	// First iteration: announce, then block until the test releases us with
	// "go". Blocking here is what guarantees "carried" has been delivered and
	// left unconsumed before the boundary.
	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-first")); err != nil {
		return "", fmt.Errorf("announce first: %w", err)
	}
	_, _, timedOut, err := h.DurableAwaitSignals([]string{"go"}, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	if timedOut {
		return `{"outcome":"never-released","iteration":1}`, nil
	}

	next := fmt.Sprintf(`{"key":%q,"timeoutMs":%d,"second":1}`, key, timeoutMs)
	if err := h.ContinueAsNew(next); err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	return `{"outcome":"continue-did-not-take-effect","iteration":1}`, nil
}
