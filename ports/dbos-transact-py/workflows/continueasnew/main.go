// Package main is the workflow under test for continue-as-new.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleContinueAsNew records that this iteration ran, then either continues
// as a new run with a decremented counter, or stops.
//
// Each iteration announces itself to the fixture service under the SAME key,
// so the call count is the number of iterations that actually executed. That
// is the assertion continue-as-new needs and the one a returned value cannot
// make: the final run's result says nothing about how many predecessors there
// were, and a chain that silently stopped after one iteration returns exactly
// what a complete chain returns.
//
// The workflow id is returned too. Continue-as-new starts a NEW RUN of the
// SAME workflow, so the id must survive the transition -- a chain that changes
// identity halfway has lost the thing every durable guarantee is keyed on, and
// nothing in the mechanism would object.
func HandleContinueAsNew(h cleat.HostCalls, key string, remaining int) (string, error) {
	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key)); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	if remaining > 1 {
		next := fmt.Sprintf(`{"key":%q,"remaining":%d}`, key, remaining-1)
		if err := h.ContinueAsNew(next); err != nil {
			return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
		}
		// Reached only if ContinueAsNew did not take effect. Saying so is
		// worth more than falling through to the success path, which would
		// make a no-op look like a completed chain.
		return `{"outcome":"continue-did-not-take-effect"}`, nil
	}

	return fmt.Sprintf(`{"outcome":"finished","workflowId":%q}`, h.WorkflowID()), nil
}
