// Package main is the workflow under test for durable-call retries.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleRetry makes one durable call under a retry policy and reports how it
// ended.
//
// `service` selects the failure mode:
//
//	"no-such-service-for-port-tests"  unresolvable -> PERMANENT, never retried
//	"flaky"                           the fixture  -> 503 while failing, so
//	                                                 TRANSIENT and retried
//
// The fixture counts calls by `key` and returns 503 for the first `failtimes`
// of them, which is what makes the retryable half observable at all: an
// unresolvable service fails once and stops, so without it a port can only see
// the permanent path. See scripts/fixture-service.py.
//
// No CallOptions.Timeout, deliberately. That field takes an SDK path spawning a
// goroutine and selecting on time.After (cleat 3.225), a determinism hazard and
// a separate defect a retry test should not be entangled with.
func HandleRetry(h cleat.HostCalls, service string, key string, attempts int, intervalMs int, failTimes int) (string, error) {
	req := fmt.Sprintf(`{"key":%q,"fail_times":%d}`, key, failTimes)

	resp, err := h.DurableCallWithOptions(cleat.CallOptions{
		Retry: &cleat.RetryPolicy{
			MaxAttempts:     attempts,
			InitialInterval: time.Duration(intervalMs) * time.Millisecond,
			// MaxInterval must be set. The host clamps each backoff to it
			// (engine/durablecalls.go), so a policy that leaves it at its zero
			// value has every wait clamped to 0 and then raised to the 1ms
			// floor -- retries happen, immediately, and the configured interval
			// is silently ignored. Measured before this line existed: three
			// attempts with a 10s interval completed in 276ms.
			MaxInterval:        time.Duration(intervalMs) * time.Millisecond,
			BackoffCoefficient: 1.0,
		},
	}, service, "op", req)

	if err != nil {
		return fmt.Sprintf(`{"outcome":"failed","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	return fmt.Sprintf(`{"outcome":"succeeded","response":%s}`, resp), nil
}
