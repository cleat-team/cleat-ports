// Package main is the workflow under test for version reporting.
package main

import (
	"fmt"
	"time"

	"github.com/cleat-team/cleat/cleat"
)

// HandleMinVersion reports Version and MinVersion on both sides of a suspension.
//
// The pair is the test. Either number alone is unfalsifiable -- any integer
// looks plausible -- so what is asserted is that they are the SAME either side
// of a suspension, and that MinVersion does not exceed Version.
//
// Both come from the workflow instance row, via WithWorkflowState at
// cmd/cleat-worker/setup.go:1620 (`minVersion: wf.MinVersion`). If that option
// were ever unwired, MinVersion would silently return the literal 1 from
// engine/lifecycle.go:97 rather than failing -- which is why "it returned a
// number" proves nothing on its own, and why the deployed version is compared
// against what the caller was told.
func HandleMinVersion(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	beforeVersion := h.Version()
	beforeMin := h.MinVersion()

	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-first")); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	h.DurableSleep(time.Duration(sleepMs) * time.Millisecond)

	return fmt.Sprintf(
		`{"beforeVersion":%d,"beforeMin":%d,"afterVersion":%d,"afterMin":%d}`,
		beforeVersion, beforeMin, h.Version(), h.MinVersion()), nil
}
