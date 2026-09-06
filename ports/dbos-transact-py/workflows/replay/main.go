// Package main is the workflow under test for replay determinism.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleReplayIdentity captures the clock through SideEffect, suspends, then
// reads the clock again, and returns both.
//
// This is cleat's central claim made observable: re-execute from step 0 on
// resume, serving completed durable work from history rather than redoing it.
//
//	cached  the clock at first execution, recorded by SideEffect
//	fresh   the clock after the suspension
//	fresh - cached >= ms   iff the cached value survived the replay
//
// If SideEffect recomputed instead of replaying, both readings would land in
// the same post-resume instant and the gap would collapse to roughly zero.
//
// h.Now() rather than time.Now(): cleat vet E003 rejects the latter. Until
// cleat#787 that advice was broken -- created_at held the moment of the write
// rather than the moment of the event, LoadEventHistory reconstructs
// TimestampMs from it, and execSession.Now() returns that, so h.Now() differed
// across replay by however long the flush took and SideEffect failed the
// workflow for a divergence the engine had introduced itself.
//
// Deliberately NOT h.NewUUID(): it returned a constant zero UUID in every
// compiled workflow until cleat#786, and a constant survives replay perfectly,
// so a test built on it passes whatever the engine does. That is how the first
// version of this test passed while asserting nothing.
func HandleReplayIdentity(h cleat.HostCalls, ms int) (string, error) {
	// An anchor event before the clock is read, and it is not decoration.
	//
	// execSession.Now returns the previous event's timestamp when one exists,
	// and otherwise the session's seed. seedNowMs takes that seed from
	// replayHistory[0].TimestampMs on a resume but from the wall clock on the
	// first execution -- so a workflow whose FIRST action reads the clock gets
	// the moment it asked on the original run and the moment the first event
	// was recorded on the replay. Measured at 109ms apart; inside a SideEffect
	// that is fatal. Reported on cleat#776.
	//
	// Recording anything first puts both runs on the history path and the
	// reading is stable. The test below asserts the replay guarantee, not that
	// hole, so it is anchored rather than left to trip over it.
	if _, err := h.SideEffect(func() (string, error) { return "anchor", nil }); err != nil {
		return "", fmt.Errorf("anchor: %w", err)
	}

	cached, err := h.SideEffect(func() (string, error) {
		return fmt.Sprintf("%d", h.Now().UnixMilli()), nil
	})
	if err != nil {
		return "", fmt.Errorf("side effect: %w", err)
	}

	h.DurableLog("replay-identity: cached " + cached)
	h.DurableSleepMs(int64(ms))

	fresh := fmt.Sprintf("%d", h.Now().UnixMilli())
	h.DurableLog("replay-identity: fresh " + fresh)

	return fmt.Sprintf(`{"cached":%q,"fresh":%q}`, cached, fresh), nil
}
