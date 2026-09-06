// Package main is the workflow under test for signal-await timeouts.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSignalTimeout waits for a signal nobody will ever send.
//
// It must come back with timedOut set once the timeout has elapsed. This is
// the control for cleat#814, which is about the promise await re-arming its
// deadline on every wake: the signal await is written the same way -- record
// the await, suspend with Until = now + timeout -- so the question is whether
// the same defect is there, or whether signals have a timeout path that
// promises are missing.
func HandleSignalTimeout(h cleat.HostCalls, timeoutMs int) (string, error) {
	name, payload, timedOut, err := h.DurableAwaitSignals([]string{"never-sent"}, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	if timedOut {
		return `{"outcome":"timedout"}`, nil
	}
	return fmt.Sprintf(`{"outcome":"signalled","name":%q,"payload":%q}`, name, payload), nil
}
