// Package main exhausts its retries and then returns an error of its OWN
// wording, discarding the engine's.
//
// It exists to test the boundary of the discriminator cleat#902 introduced.
// Dead-lettering no longer keys off the phrase "retries exhausted"; it now
// requires a history event flagged RetriesExhausted AND that event's error text
// to appear in the workflow's final message:
//
//	ev.RetriesExhausted && ev.Err != "" && strings.Contains(errMsg, ev.Err)
//
// The typed flag is the improvement. The `Contains` is a surviving coupling,
// and it means the classification depends on the GUEST propagating the
// engine's error text rather than on anything the engine recorded.
//
// deadletter/main.go wraps with %w, so the text survives and it dead-letters.
// This one does what a real workflow is at least as likely to do -- catch the
// failure and report it in its own terms -- and asks whether the work is still
// retained for an operator.
//
// Either answer is worth having. If it dead-letters, the coupling is looser
// than it reads. If it does not, then whether a workflow is retained depends
// on how its author phrased an error, which is a property no operator can see
// and no reviewer would think to check.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

func HandleDeadLetterOpaque(h cleat.HostCalls, service string, key string, attempts int, intervalMs int) (string, error) {
	req := fmt.Sprintf(`{"key":%q,"fail_times":999}`, key)

	_, err := h.DurableCallWithOptions(cleat.CallOptions{
		Retry: &cleat.RetryPolicy{
			MaxAttempts:        attempts,
			InitialInterval:    time.Duration(intervalMs) * time.Millisecond,
			MaxInterval:        time.Duration(intervalMs) * time.Millisecond,
			BackoffCoefficient: 1.0,
		},
	}, service, "op", req)
	if err != nil {
		// Deliberately NOT %w. The engine's text is dropped entirely, which is
		// the whole point of the fixture: a workflow reporting a failure in its
		// own vocabulary rather than relaying the one it was handed.
		return "", fmt.Errorf("could not reach the billing provider")
	}
	return `{"outcome":"unexpectedly succeeded"}`, nil
}
