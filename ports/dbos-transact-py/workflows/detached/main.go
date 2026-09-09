// Package main is the workflow under test for detached execution.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleDetached starts `retrycall` fire-and-forget and returns immediately.
//
// The detached workflow calls the fixture service with `key`, so the test can
// observe that it really ran: the parent completing proves only that the
// request was accepted, and this feature spent its whole life until cleat#796
// accepting requests and starting nothing.
//
// RunDetached took a closure until then, which cannot cross the WASM ABI, so
// the method was never wired in a compiled workflow and its unwired branch
// returned nil. It worked under localdev and cleattest, which populate the
// field in-process. A conformance test that ran only against those would have
// reported this feature healthy.
// Two parameters, and the second is unused on purpose. A workflow with a
// SINGLE string parameter receives the raw input JSON rather than a named
// field -- `{"input":{"key":"ABC"}}` arrives as the string `{"key": "ABC"}`,
// matching testdata/minimal-wf, whose parameter is named `input` for that
// reason. Name binding applies only when there is more than one parameter.
// Measured; it is a rule, not a defect, and it silently produced a key that
// was a JSON object.
func HandleDetached(h cleat.HostCalls, key string, seq int) (string, error) {
	_ = seq

	// failStatus is passed explicitly even though 0 is what it defaults to.
	// This payload omitted it, and for the two hours cleat#1046 made an absent
	// int a decode error rather than a zero, the detached run died at its own
	// front door. Invisible from here: RunDetached had already returned nil, so
	// the parent still reported "requested" and only the fixture's call count
	// disagreed -- exactly the cleat#796 signature this test exists to catch,
	// produced by something else entirely. cleat#1057 restored the zero, so this
	// line is no longer load-bearing for correctness; it stays because a payload
	// that names every parameter cannot be quietly wrong about any of them.
	input := fmt.Sprintf(
		`{"service":"flaky","key":%q,"attempts":1,"intervalMs":100,"failTimes":0,`+
			`"failStatus":0}`, key)

	if err := h.RunDetached("retrycall", input); err != nil {
		return "", fmt.Errorf("run detached: %w", err)
	}
	return `{"outcome":"requested"}`, nil
}
