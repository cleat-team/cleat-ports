// Package main is the cleat port of temporalio/samples-go `timer/` and
// `sleepfor/`.
//
// Upstream's subject is that a timer is an ENGINE primitive: it survives worker
// loss, it is deterministic on replay, and it does not consult the wall clock.
// cleat states the same guarantees in prose on the Timer interface
// (cleat/runtime.go:128) in four separate claims, and this workflow exists to
// return the numbers that decide each of them rather than to assert them.
//
//  1. Now() is the timestamp of the most recent durable event.
//  2. Virtual time does NOT advance during non-durable CPU work.
//  3. Only DurableSleep advances it: after DurableSleep(5s), Now() returns
//     the PRE-SLEEP time plus 5 seconds.
//  4. At the replay frontier Now() jumps to wall-clock time.
//
// Claim 3 is the sharp one and the reason for the exact arithmetic below. If
// the engine instead set Now() from the wall clock at wake-up, a workflow that
// slept 1s on a busy worker would observe 3s -- and two replays of the same
// history would disagree, which is the whole thing durable time exists to
// prevent. "Plus the sleep" and "when it woke up" are indistinguishable on an
// idle machine and differ under load, so the test asserts the arithmetic rather
// than a tolerance.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// burn does non-durable CPU work and returns a value derived from it.
//
// The result is returned and threaded into the output so the loop cannot be
// optimised away -- a compiler free to delete it would leave the "virtual time
// does not advance during CPU work" assertion measuring nothing, and passing.
//
// A package-level function rather than an inline loop: E009 rejects calls
// through function values, and this port already carries one finding about
// that (ISSUES.md #1).
func burn(iterations int) int {
	sum := 0
	for i := 0; i < iterations; i++ {
		sum += i % 7
	}
	return sum
}

// HandleDurableClock samples the durable clock at four points and reports all
// of them, so the test can do the arithmetic.
//
//	t0  at entry
//	t1  after CPU work, no durable event between -- must equal t0
//	t2  after a durable call -- a new event, so this may advance
//	t3  after DurableSleepMs(sleepMs) -- must be t2 + sleepMs
func HandleDurableClock(h cleat.HostCalls, key string, sleepMs int) (string, error) {
	t0 := h.NowMs()

	burned := burn(2000000)

	t1 := h.NowMs()

	if _, err := h.DurableCall("clock", "Mark", fmt.Sprintf(`{"key":%q}`, key)); err != nil {
		return "", fmt.Errorf("mark: %w", err)
	}
	t2 := h.NowMs()

	h.DurableSleepMs(int64(sleepMs))
	t3 := h.NowMs()

	return fmt.Sprintf(`{"key":%q,"t0":%d,"t1":%d,"t2":%d,"t3":%d,"burned":%d}`,
		key, t0, t1, t2, t3, burned), nil
}
