// Package main is the child half of the cleat port of
// temporalio/samples-go `childworkflow-continueasnew/`.
//
// The child continues-as-new until its counter runs out. Each iteration
// announces itself to the fixture, so the test can count iterations from
// outside rather than trusting the final result to report them.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCasnChild announces itself, then either continues as new with one
// fewer iteration or returns.
//
// The announcement comes FIRST, before the ContinueAsNew, because a
// continue-as-new that never returns would otherwise leave no trace that the
// iteration ran at all -- and "the chain stopped early" and "the chain ran but
// recorded nothing" are the two outcomes this test has to tell apart.
func HandleCasnChild(h cleat.HostCalls, key string, iterations int) (string, error) {
	if _, err := h.DurableCall("casn", "Iteration", fmt.Sprintf(`{"key":%q}`, key)); err != nil {
		return "", fmt.Errorf("announcing iteration: %w", err)
	}

	if iterations > 1 {
		if err := h.ContinueAsNew(fmt.Sprintf(`{"key":%q,"iterations":%d}`, key, iterations-1)); err != nil {
			return "", fmt.Errorf("continue as new: %w", err)
		}
		// ContinueAsNew suspends; this return is not reached on the live path.
		return "", nil
	}

	return fmt.Sprintf(`{"key":%q,"final":true}`, key), nil
}
