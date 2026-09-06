// Package main is the workflow that waits to be signalled by another run.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSignalReceiver announces its run id, then waits for a named signal.
//
// The announcement is a durable call to the fixture service keyed by the
// caller-supplied `key`, and it exists so the test can know the receiver has
// REACHED the wait before anything signals it. Signalling a run that has not
// got there yet is a different case -- whether a signal delivered early is
// held for the eventual await -- and mixing the two would leave a failure
// unable to say which one broke.
func HandleSignalReceiver(h cleat.HostCalls, key string, timeoutMs int) (string, error) {
	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-waiting")); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	name, payload, timedOut, err := h.DurableAwaitSignals([]string{"go"}, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	if timedOut {
		return `{"outcome":"timedout"}`, nil
	}
	return fmt.Sprintf(`{"outcome":"signalled","name":%q,"payload":%q}`, name, payload), nil
}
