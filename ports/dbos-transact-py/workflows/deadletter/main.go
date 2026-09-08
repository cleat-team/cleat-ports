// Package main is the workflow under test for the dead-letter queue.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleDeadLetter exhausts its retry budget and PROPAGATES the error.
//
// The propagation is the whole point, and it is why this workflow had to exist
// rather than reusing `retrycall`. Every other workflow in this suite CATCHES
// the call error and returns a result describing it, so every other workflow
// completes `done` however badly the call went -- and the dead-letter queue was
// therefore unreachable from the entire port suite. Three endpoints
// (/api/dead-letters, .../reprocess, .../terminate) had never been called from
// a test because nothing could get a row into the table.
//
// Returning the error is what makes the worker treat this as a terminal
// failure, and a terminal failure whose message carries "retries exhausted" is
// what sends it to the DLQ rather than to `failed` -- see cleat#902, which is
// about that decision being a substring match rather than the error CODE that
// already exists beside it.
func HandleDeadLetter(h cleat.HostCalls, service string, key string, attempts int, intervalMs int) (string, error) {
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
		// Propagated, not described. A returned error is a terminal failure;
		// a returned result is a completion.
		return "", fmt.Errorf("the call never succeeded: %w", err)
	}
	return `{"outcome":"unexpectedly succeeded"}`, nil
}
