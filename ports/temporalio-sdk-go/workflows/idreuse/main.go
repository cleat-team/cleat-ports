// Package main is the workflow the duplicate-start cases run under.
package main

import (
	"errors"
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleReuse waits, then either succeeds or fails, on the caller's
// instruction.
//
// ONE definition covers all three arms of the duplicate-start answer --
// running, done, failed -- and that is the point rather than an economy. The
// three assertions differ only in what the first start's run is doing when the
// second start arrives; if each arm had its own workflow, a difference in the
// answer could be attributed to the definition instead of to the run's state,
// which is the one thing these cases are about.
//
// The sleep is a DURABLE one. A busy-wait would hold the worker's execution
// slot and the second start would be racing the scheduler rather than reading
// the first run's status; a durable sleep parks the run in `running` with the
// worker free, which is the state a caller retrying a lost start actually finds.
func HandleReuse(h cleat.HostCalls, marker string, sleepMs int, fail int) (string, error) {
	if sleepMs > 0 {
		h.DurableSleepMs(int64(sleepMs))
	}
	if fail != 0 {
		// The marker travels in the failure message because the assertion is
		// not "it failed" -- it is that the duplicate start reports THIS run's
		// error rather than a generic one, and only a string that could have
		// come from nowhere else can show that.
		return "", errors.New("idreuse failed on purpose: " + marker)
	}
	return fmt.Sprintf(`{"outcome":"finished","marker":%q}`, marker), nil
}
