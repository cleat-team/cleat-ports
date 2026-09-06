// Package main is the workflow that attempts a lock another run may hold.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleLockTry attempts the lock once and reports whether it got it.
//
// It releases immediately on success, so the same workflow can be used to ask
// both questions the test needs -- "is it held right now" and "was it released"
// -- without a second deploy whose behaviour could differ.
//
// ttlMs exists to give this entry point a SECOND parameter, and that is not
// cosmetic. Arguments bind by exact Go parameter name, EXCEPT when the entry
// point takes a single string: that one receives the raw input JSON instead.
// With `key` alone the lock key became the literal {"key":"lock-abc"}, and the
// acquire failed with `cleat_acquire_lock: error 1` for every call, contended
// or not -- which reads like a broken lock and is a broken argument.
func HandleLockTry(h cleat.HostCalls, key string, ttlMs int) (string, error) {
	acquired, err := h.AcquireLockMs("lock-"+key, int64(ttlMs))
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	if acquired {
		if err := h.ReleaseLock("lock-" + key); err != nil {
			return fmt.Sprintf(`{"acquired":true,"release_error":%q}`, fmt.Sprintf("%v", err)), nil
		}
	}
	return fmt.Sprintf(`{"acquired":%t}`, acquired), nil
}
