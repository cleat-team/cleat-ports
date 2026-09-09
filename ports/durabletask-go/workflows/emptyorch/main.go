// Package main is an orchestration that does no work at all.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleEmptyOrch returns without making a single host call.
//
// Upstream's Test_EmptyOrchestration asserts that an orchestration with no
// activities still reaches a completed status with its output recorded -- that
// "nothing to do" is a normal terminal outcome rather than a stall or an
// error.
//
// It takes the HostCalls parameter and does not use it on purpose: cleat binds
// entry points by signature, and a workflow that declares no host calls is
// still a workflow. Dropping the parameter would be testing the binder rather
// than the engine.
func HandleEmptyOrch(h cleat.HostCalls, marker string, n int) (string, error) {
	return fmt.Sprintf(`{"outcome":"empty","marker":%q,"n":%d}`, marker, n), nil
}
