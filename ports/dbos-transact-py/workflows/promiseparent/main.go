// Package main is the parent workflow for promise settlement.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePromise creates a promise, has a child settle it, and awaits it.
//
//	mode == "resolve"  the child resolves; the awaited value comes back
//	mode == "reject"   the child rejects; the await reports the failure
//	mode == "timeout"  no child is spawned, so the await must time out
//
// The timeout mode is what makes the other two mean anything. Without it a
// promise that was never settled and an await that returns immediately are
// indistinguishable from a promise that was settled correctly.
func HandlePromise(h cleat.HostCalls, mode string, timeoutMs int) (string, error) {
	id, err := h.CreatePromise("port-promise")
	if err != nil {
		return "", fmt.Errorf("create promise: %w", err)
	}

	if mode != "timeout" {
		input := fmt.Sprintf(`{"promiseId":%q,"mode":%q}`, id, mode)
		if _, err := h.ChildWorkflow("promise_settler", input); err != nil {
			return "", fmt.Errorf("spawn settler: %w", err)
		}
	}

	result, timedOut, err := h.AwaitPromiseMs(id, int64(timeoutMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	if timedOut {
		return `{"outcome":"timedout"}`, nil
	}
	return fmt.Sprintf(`{"outcome":"resolved","result":%q}`, result), nil
}
