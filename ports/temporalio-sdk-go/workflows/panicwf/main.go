// Package main panics on purpose.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePanicWF panics with a caller-supplied marker when `shouldPanic` is
// non-zero, and returns normally otherwise.
//
// TWO BRANCHES RATHER THAN AN UNCONDITIONAL PANIC, and the second is the
// control: "the run failed" is satisfied by a workflow that cannot start, a
// definition that will not load, or a harness pointed at the wrong worker. The
// non-panicking branch of the same definition, started the same way, is what
// separates "this workflow fails when it panics" from "this workflow fails".
//
// The marker travels inside the panic value because the assertion is not that
// the run failed -- it is that the PANIC'S OWN message reaches the caller, and
// only a string that could have come from nowhere else shows that.
func HandlePanicWF(h cleat.HostCalls, marker string, shouldPanic int) (string, error) {
	if shouldPanic != 0 {
		panic("simulated panic: " + marker)
	}
	return fmt.Sprintf(`{"outcome":"returned-normally","marker":%q}`, marker), nil
}
