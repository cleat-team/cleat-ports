// Package main is the SECOND version of the workflow used by the
// version-pinning test. Its twin, workflows/versionone, is deployed under the
// same definition name with a lower embedded version.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleVersionMark reports which build of itself ran, then suspends.
//
// The marker is a literal, not a host call: the question is which BYTES the
// engine executed, and anything the engine reports about itself would be
// answering with the version it believes rather than the version that ran.
//
// The sleep is what makes the test possible at all. It has to be long enough
// for a second version to be deployed while this run is parked mid-body, so
// the run spans the deploy rather than finishing before it -- a run that
// completes first proves nothing about what a suspended run resumes on.
//
// Reported twice, before and after the suspension, and both must agree. One
// reading cannot distinguish "resumed on the old bytes" from "resumed on the
// new bytes and the new bytes happen to say the same thing at the end".
func HandleVersionMark(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	before := "two"

	h.DurableSleepMs(int64(sleepMs))

	after := "two"

	return fmt.Sprintf(`{"before":%q,"after":%q,"key":%q}`, before, after, key), nil
}
