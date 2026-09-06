// Package main is the workflow under test for replay behaviour.
package main

import "github.com/cleat-team/cleat/cleat"

// HandleReplayIdentity suspends for `ms` and reports completion.
//
// It once captured a value through SideEffect, to witness that completed work
// is not redone across a replay. That cannot be written against cleat today --
// see the module docstring in tests/test_replay.py for the three primitives
// tried and why each one fails -- so this asserts only the half that is
// observable from outside: that the run really suspends.
func HandleReplayIdentity(h cleat.HostCalls, ms int) (string, error) {
	h.DurableLog("replay-identity: start")
	h.DurableSleepMs(int64(ms))
	h.DurableLog("replay-identity: resumed")
	return `{"status":"done"}`, nil
}
