// Package main is the workflow under test for durable-call retries.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleRetry makes one durable call to a service that does not exist, under a
// retry policy, and reports how it ended.
//
// The target is deliberately unresolvable: a call that always fails is the only
// way to observe the full policy without a fixture service that can be told to
// fail a set number of times. What is asserted from outside is the wall-clock
// cost of the backoff, which is why `attempts` and `interval_ms` are inputs.
//
// No Timeout is set, deliberately. CallOptions.Timeout takes an SDK path that
// spawns a goroutine and selects on time.After (cleat#789 / 3.225), which is a
// determinism hazard and a separate defect; a retry test should not be
// entangled with it.
func HandleRetry(h cleat.HostCalls, attempts int, intervalMs int) (string, error) {
	_, err := h.DurableCallWithOptions(cleat.CallOptions{
		Retry: &cleat.RetryPolicy{
			MaxAttempts:        attempts,
			InitialInterval:    time.Duration(intervalMs) * time.Millisecond,
			BackoffCoefficient: 1.0,
		},
	}, "no-such-service-for-port-tests", "op", "{}")

	if err != nil {
		return fmt.Sprintf(`{"outcome":"failed","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	return `{"outcome":"unexpected_success"}`, nil
}
