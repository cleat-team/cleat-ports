// Package main is the workflow under test for defers on a NON-normal exit.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleDeferDeadLetter registers a cleanup and then exhausts its retry budget,
// propagating the error.
//
// It exists because every defer fixture in this suite ends the ordinary way --
// the body returns and the entry-point wrapper drains the defer table on its
// way out -- so nothing here could ask what happens to a defer when the
// workflow ends some OTHER way. cleat#1152 measured two operator endpoints
// (force-complete, force-fail) skipping the defers they owed, and the open
// question that issue names is whether ANY non-normal exit runs them. That
// cannot be answered without a workflow that both owes a defer and reaches a
// non-normal end, which is this one.
//
// Two questions it can answer, and the second is free once the first exists:
//
//  1. does a run that dead-letters run its defers?
//  2. does terminating it from the dead-letter queue run them?
//
// (2) is the one that matters for cleat#1153: the dead-letter terminate route
// is one of only two callers of TerminateWorkflow, the two-phase MARK/FINALIZE
// path, so it is the natural control for "the mechanism works and those two
// endpoints merely bypass it".
//
// The bodyKey send is what makes a later assertion mean something: it proves
// the body RAN and therefore that the defer was registered, so a missing
// deferKey call is a skipped cleanup rather than a workflow that never started.
// Without it, "the defer did not arrive" and "nothing ever executed" are the
// same observation -- the vacuity ports#172 turned on.
func HandleDeferDeadLetter(h cleat.HostCalls, service string, bodyKey string, deferKey string, attempts int, intervalMs int) (string, error) {
	if err := h.DurableSend("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, bodyKey)); err != nil {
		return "", err
	}

	if _, err := h.DurableDeferFunc(func() {
		h.DurableSend("flaky", "op", fmt.Sprintf(`{"key":%q,"fail_times":0}`, deferKey))
	}); err != nil {
		return "", err
	}

	// Exhaust the budget against a call that never succeeds, then PROPAGATE.
	// Returning the error is what makes this a terminal failure, and a terminal
	// failure carrying "retries exhausted" is what routes it to the DLQ rather
	// than to `failed` -- the same mechanism deadletter/main.go documents.
	_, err := h.DurableCallWithOptions(cleat.CallOptions{
		Retry: &cleat.RetryPolicy{
			MaxAttempts:        attempts,
			InitialInterval:    time.Duration(intervalMs) * time.Millisecond,
			MaxInterval:        time.Duration(intervalMs) * time.Millisecond,
			BackoffCoefficient: 1.0,
		},
	}, service, "op", fmt.Sprintf(`{"key":%q,"fail_times":999}`, deferKey+"-call"))
	if err != nil {
		return "", fmt.Errorf("the call never succeeded: %w", err)
	}
	return `{"outcome":"unexpectedly succeeded"}`, nil
}
