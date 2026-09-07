// Package main is the workflow under test for non-blocking signal polling.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePollSignal polls for a signal before one is sent and again after.
//
// PollSignal is the non-blocking counterpart to DurableAwaitSignals: it must
// return immediately with found=false rather than suspending, and it must see
// a signal that arrived while the workflow was elsewhere.
//
// Both polls are asserted, and the first is the one that carries the weight.
// An implementation that simply reported found=true unconditionally would pass
// a test that only checked the second, and an implementation that always
// suspended would never reach the announcement at all. The pair distinguishes
// "polling works" from "a signal eventually arrives", which are different
// claims.
//
// The announcement between the polls is a durable call to the fixture keyed by
// `key`, so the test knows the first poll has happened before it sends
// anything. Without it the test would be racing the workflow, and a signal
// that arrived before the first poll would make that poll return true --
// failing for a reason that is about test timing rather than about the code.
func HandlePollSignal(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	_, foundBefore, err := h.PollSignal("go")
	if err != nil {
		return "", fmt.Errorf("first poll: %w", err)
	}

	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-polled")); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	// Suspends, so the second poll runs in a later segment against replayed
	// history -- which is where a poll that recorded nothing would go wrong.
	h.DurableSleep(time.Duration(sleepMs) * time.Millisecond)

	payload, foundAfter, err := h.PollSignal("go")
	if err != nil {
		return "", fmt.Errorf("second poll: %w", err)
	}

	return fmt.Sprintf(`{"before":%t,"after":%t,"payload":%q}`,
		foundBefore, foundAfter, payload), nil
}
