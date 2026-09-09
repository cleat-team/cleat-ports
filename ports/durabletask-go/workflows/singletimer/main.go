// Package main is an orchestration whose only step is a durable timer.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleSingleTimer sleeps once, durably, and reports that it resumed.
//
// Upstream's Test_SingleTimer asserts that an orchestration whose only work is
// a timer completes after the timer fires -- the timer is durable state, not a
// thread parked in memory, so the run survives the wait.
//
// The `resumed` marker is what makes the assertion more than "it finished":
// it is produced AFTER the sleep, so a run that returned early without waiting
// could not carry it.
func HandleSingleTimer(h cleat.HostCalls, marker string, sleepMs int) (string, error) {
	h.DurableSleepMs(int64(sleepMs))
	return fmt.Sprintf(`{"outcome":"resumed","marker":%q}`, marker), nil
}
