// Package main is the workflow under test for cancellation.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCancellable runs for roughly `ms`, optionally checking for cancellation.
//
// `poll` selects between the two behaviours a single deploy has to cover:
//
//	poll != 0  check PollCancellation between sleeps and return early
//	poll == 0  ignore cancellation entirely and run to completion
//
// The second is not a straw man. Cleat's cancellation is cooperative --
// PollCancellation returns (bool, string) and the workflow decides what to do --
// so "cancel a workflow that never asks" is a real thing an author can write,
// and what the engine does with it is the behaviour worth pinning down.
func HandleCancellable(h cleat.HostCalls, ms int, poll int) (string, error) {
	const step = 250

	elapsed := 0
	for elapsed < ms {
		if poll != 0 {
			if cancelled, reason := h.PollCancellation(); cancelled {
				h.DurableLog("cancellable: observed cancellation: " + reason)
				return fmt.Sprintf(`{"outcome":"cancelled","reason":%q,"elapsed_ms":%d}`,
					reason, elapsed), nil
			}
		}
		h.DurableSleepMs(step)
		elapsed += step
	}

	return fmt.Sprintf(`{"outcome":"completed","elapsed_ms":%d}`, elapsed), nil
}
