// Package main must NOT build. It is the closest literal port of
// temporalio/samples-go `goroutine/`, which uses workflow.Go to run work
// concurrently inside a single workflow.
//
// Temporal schedules those goroutines cooperatively and deterministically, so
// the pattern is safe there. cleat has no equivalent and forbids the construct
// outright: workflow code is single-threaded by design. The sample therefore
// cannot be ported as written, and this file exists to prove that the refusal
// is enforced by the toolchain rather than only documented.
package main

import "github.com/cleat-team/cleat/cleat"

func HandleGoroutine(h cleat.HostCalls, key string) (string, error) {
	done := make(chan string, 1)
	go func() {
		done <- "finished"
	}()
	return <-done, nil
}
