// Package main is the child half of the samples-go child-workflow port.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleChildSleeper announces itself to the fixture, sleeps, and announces
// again.
//
// The two calls are the whole design. A parent-close policy decides whether a
// RUNNING child keeps running, so the assertion is about what the child does
// AFTER the parent closes -- and the child's final status is not enough to
// show that. A child terminated at 300ms and a child that finished normally
// can both end up in a terminal state; only "did the second call arrive"
// distinguishes them.
//
// The sleep must outlast the parent's close by a comfortable margin, or an
// ABANDON child that was going to finish anyway proves nothing about ABANDON.
func HandleChildSleeper(h cleat.HostCalls, key string, ms int) (string, error) {
	if _, err := h.DurableCall("child", "Started", fmt.Sprintf(`{"key":%q}`, key)); err != nil {
		return "", fmt.Errorf("announcing start: %w", err)
	}

	h.DurableSleepMs(int64(ms))

	if _, err := h.DurableCall("child", "Finished", fmt.Sprintf(`{"key":%q}`, key)); err != nil {
		return "", fmt.Errorf("announcing finish: %w", err)
	}
	return fmt.Sprintf(`{"key":%q,"finished":true}`, key), nil
}
