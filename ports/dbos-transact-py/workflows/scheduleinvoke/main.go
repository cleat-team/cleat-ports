// Package main is the workflow under test for delayed service invocation.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleScheduleInvoke asks the host to call a service after a delay, then
// sleeps past that delay so the workflow is still alive when it fires.
//
// The sleep matters twice. It keeps the run open across the moment the
// invocation is due, and it forces a suspension -- so the schedule is recorded
// in one segment and fires while the workflow is in another, which is the
// arrangement a durable engine has to get right.
func HandleScheduleInvoke(h cleat.HostCalls, invokeKey string, delayMs int, sleepMs int) (string, error) {
	if err := h.ScheduleInvoke("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, invokeKey), int64(delayMs)); err != nil {
		return "", fmt.Errorf("ScheduleInvoke: %w", err)
	}
	h.DurableSleepMs(int64(sleepMs))
	return `{"scheduled":true}`, nil
}
