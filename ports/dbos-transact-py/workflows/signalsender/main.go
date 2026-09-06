// Package main is the workflow that signals another run.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSignalSender delivers one signal to a run it is told about.
//
// Sending from inside a workflow rather than over the API is the point: this
// is the cross-workflow path, the same shape as promise settlement, which was
// entirely non-functional until cleat#813 -- a settler ran to completion,
// reported success, and had no effect. A sender that returns nil proves
// nothing on its own, so the assertion lives in the RECEIVER's result.
func HandleSignalSender(h cleat.HostCalls, targetRunID, payload string) (string, error) {
	if err := h.SignalWorkflow(targetRunID, "go", payload); err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	return `{"outcome":"sent"}`, nil
}
