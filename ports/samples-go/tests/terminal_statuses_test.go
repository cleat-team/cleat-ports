package tests

import "testing"

// The harness's idea of "settled" is a vocabulary it shares with the engine,
// and nothing checked that the two agreed. This does, without a database.
//
// It exists because both readers of that vocabulary were wrong in the same two
// ways at once, and neither wrongness could fail a test:
//
//   - "dead_lettered" was absent, so awaitTerminal polled a settled run to its
//     deadline and then failed with a message naming the terminal status it
//     had been waiting for, while isRunning silently answered true forever.
//   - "cancelled" was present and is not a workflow status at all, so that
//     branch had never matched anything.
//
// An absent member fails slowly and a fictional one never fails, which is why
// four plausible names survived: the set reads as an enumeration of "the ways
// a run ends" and was never counted against the engine.
func TestTheTerminalSetIsTheEnginesAndNotAPlausibleGuess(t *testing.T) {
	// cmd/cleat-worker/server.go, isTerminalStatus, less "terminating" --
	// see terminalStatuses for why that one is deliberately excluded here.
	for _, want := range []string{"done", "failed", "terminated", "dead_lettered"} {
		if !terminalStatuses[want] {
			t.Errorf("%q is a status the engine settles runs in, and the harness does not "+
				"treat it as terminal.\n\nawaitTerminal will poll such a run until its "+
				"deadline and then report a timeout naming that very status; isRunning "+
				"will report it as still running, forever.", want)
		}
	}

	// A status the engine never writes. The cancel endpoint answers
	// {"status":"cancellation_requested"}, and engine/errors.go's "cancelled"
	// is an ErrorCode -- the Python port pins this in
	// test_a_cancelled_workflow_still_reports_status_done.
	if terminalStatuses["cancelled"] {
		t.Error(`"cancelled" is not a workflow status; the engine never writes it. ` +
			`A member that cannot match is worse than useless here: it padded this set ` +
			`to four plausible names, which is why nobody noticed "dead_lettered" was missing.`)
	}

	// "terminating" means the defer phase is still running and the final
	// status is not yet written. awaitTerminal returning it would hand callers
	// a non-final status; isRunning must call it running. Both want it out.
	if terminalStatuses["terminating"] {
		t.Error(`"terminating" must not be terminal here: the defer phase is still ` +
			`running and the final status is not written yet, so awaitTerminal would ` +
			`return a run that has not settled.`)
	}

	if n := len(terminalStatuses); n != 4 {
		t.Errorf("terminalStatuses has %d members, want 4 -- a name added without a "+
			"case above is a name nothing checks against the engine", n)
	}
}
