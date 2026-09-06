// Package main is the workflow that holds a distributed lock.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleLockHolder takes a lock, announces that it holds it, suspends, and
// releases.
//
// The announcement is a real durable call to the fixture service rather than
// query state, and that is deliberate: the test needs to know the lock is HELD
// before it attempts the second acquire, and a timing guess would make the
// assertion flaky in the direction that passes. Query state would work too,
// but SetQueryState is itself untested here, and a lock test that fails
// because query state is broken says nothing about locks.
//
// DurableSleepMs suspends the run rather than blocking a worker slot. That is
// the point of the test: the lock must be held by the RUN, across a
// suspension, not by whichever worker happens to be executing it. A lock that
// only holds while a worker is busy is not a distributed lock.
func HandleLockHolder(h cleat.HostCalls, key string, holdMs int) (string, error) {
	acquired, err := h.AcquireLockMs("lock-"+key, 120000)
	if err != nil {
		return fmt.Sprintf(`{"outcome":"error","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	if !acquired {
		return `{"outcome":"not-acquired"}`, nil
	}

	if _, err := h.DurableCall("flaky", "op",
		fmt.Sprintf(`{"key":%q,"fail_times":0}`, key+"-held")); err != nil {
		return "", fmt.Errorf("announce: %w", err)
	}

	h.DurableSleepMs(int64(holdMs))

	if err := h.ReleaseLock("lock-" + key); err != nil {
		return fmt.Sprintf(`{"outcome":"release-failed","error":%q}`, fmt.Sprintf("%v", err)), nil
	}
	return `{"outcome":"held-and-released"}`, nil
}
