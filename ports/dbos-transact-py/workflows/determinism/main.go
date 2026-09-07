// Package main is the workflow under test for replay determinism of the
// engine's non-durable readings: randomness and workflow identity.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleDeterminism captures randomness and identity through SideEffect,
// suspends, and reads identity again.
//
// SideEffect does not cache, it VALIDATES: on replay it recomputes the closure
// and compares the result against history, failing the workflow on a
// mismatch. So a value that is not stable across replay does not need an
// assertion here at all -- the run simply does not reach `done`. That makes
// this workflow's own completion the assertion, and the returned values are
// there to check the OTHER half.
//
// The other half is the trap this is written around. h.NewUUID() returned a
// constant zero UUID in every compiled workflow until cleat#786, and a
// constant survives replay perfectly -- so a determinism test built on one
// passes whatever the engine does. Two separate draws are therefore taken and
// returned, and the test requires them to differ. Without that, an
// unwired Random returning 0 twice would look like flawless determinism.
func HandleDeterminism(h cleat.HostCalls, ms int) (string, error) {
	// Anchor, for the reason the replay workflow gives: a workflow whose first
	// action reads the clock or the seed gets a different anchor on replay.
	if _, err := h.SideEffect(func() (string, error) { return "anchor", nil }); err != nil {
		return "", fmt.Errorf("anchor: %w", err)
	}

	// Two draws, recorded separately. Both must survive replay, and they must
	// not be equal to each other.
	r1, err := h.SideEffect(func() (string, error) {
		return fmt.Sprintf("%d", h.Random()), nil
	})
	if err != nil {
		return "", fmt.Errorf("random 1: %w", err)
	}
	r2, err := h.SideEffect(func() (string, error) {
		return fmt.Sprintf("%d", h.Random()), nil
	})
	if err != nil {
		return "", fmt.Errorf("random 2: %w", err)
	}

	// Identity, captured before the suspension.
	wfBefore, err := h.SideEffect(func() (string, error) { return h.WorkflowID(), nil })
	if err != nil {
		return "", fmt.Errorf("workflow id: %w", err)
	}
	runBefore, err := h.SideEffect(func() (string, error) { return h.RunID(), nil })
	if err != nil {
		return "", fmt.Errorf("run id: %w", err)
	}

	h.DurableSleepMs(int64(ms))

	// Read again after the suspension, OUTSIDE a SideEffect. Identity is not
	// durable work and is not served from history; it is answered by the
	// session. A workflow that woke up as a different run would report it
	// here, and nothing in the replay machinery would have objected.
	return fmt.Sprintf(
		`{"r1":%q,"r2":%q,"wfBefore":%q,"runBefore":%q,"wfAfter":%q,"runAfter":%q,"version":%d}`,
		r1, r2, wfBefore, runBefore, h.WorkflowID(), h.RunID(), h.Version()), nil
}
