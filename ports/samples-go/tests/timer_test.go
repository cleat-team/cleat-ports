package tests

// The timer samples, ported from temporalio/samples-go `timer/` and
// `sleepfor/`.
//
// Upstream's subject is that a timer is an ENGINE primitive rather than a
// library call: deterministic on replay, and not a reading of the wall clock.
// cleat states the same guarantees in prose on the Timer interface
// (cleat/runtime.go:128). These tests turn that prose into arithmetic.
//
// The DBOS port already covers that the virtual clock ADVANCES across a sleep.
// What it does not ask is by how much, or whether anything else moves it.

import (
	"encoding/json"
	"sync"
	"testing"
	"time"
)

var (
	clockOnce sync.Once
	clockWF   string
)

func clockWorkflow(t *testing.T) string {
	t.Helper()
	clockOnce.Do(func() { clockWF = deploy(t, "durableclock", "sg_durable_clock") })
	if clockWF == "" {
		t.Fatal("the durable-clock workflow failed to deploy; see the first failure above")
	}
	return clockWF
}

type clockSample struct {
	Key            string `json:"key"`
	T0, T1, T2, T3 int64
	Burned         int `json:"burned"`
}

// runClock starts the workflow and returns its four clock readings.
func runClock(t *testing.T, sleepMs int) clockSample {
	t.Helper()
	runID := startedRunID(t, start(t, clockWorkflow(t), map[string]any{
		"key": key(t), "sleepMs": sleepMs,
	}))
	final := awaitTerminal(t, runID, 60*time.Second)
	if final["status"] != "done" {
		t.Fatalf("the clock workflow ended %v: %v", final["status"], final["error"])
	}
	result, _ := final["result"].(string)

	var raw struct {
		Key    string `json:"key"`
		T0     int64  `json:"t0"`
		T1     int64  `json:"t1"`
		T2     int64  `json:"t2"`
		T3     int64  `json:"t3"`
		Burned int    `json:"burned"`
	}
	if err := json.Unmarshal([]byte(result), &raw); err != nil {
		t.Fatalf("could not read the clock samples from %q: %v", result, err)
	}
	if raw.Burned == 0 {
		t.Fatal("the CPU-work loop returned 0, so it may have been optimised away; " +
			"the 'time does not advance during CPU work' assertion would then be " +
			"measuring nothing and passing")
	}
	return clockSample{Key: raw.Key, T0: raw.T0, T1: raw.T1, T2: raw.T2, T3: raw.T3, Burned: raw.Burned}
}

// TestVirtualTimeDoesNotAdvanceDuringCpuWork is claim 2 of the Timer contract.
//
// If Now() read the wall clock, two calls either side of two million loop
// iterations would differ. They must not: virtual time is the timestamp of the
// last durable EVENT, and CPU work records none.
//
// This is the guarantee that makes replay work at all. A workflow branching on
// elapsed time between events would take a different branch on replay, and
// nothing else in the system would notice.
func TestVirtualTimeDoesNotAdvanceDuringCpuWork(t *testing.T) {
	c := runClock(t, 500)
	if c.T1 != c.T0 {
		t.Errorf("Now() advanced by %dms across non-durable CPU work (t0=%d t1=%d).\n"+
			"Virtual time must only move on a durable event; if it reads the wall "+
			"clock here, a workflow that branches on elapsed time replays differently "+
			"than it ran.", c.T1-c.T0, c.T0, c.T1)
	}
}

// TestASleepAdvancesTheClockByExactlyTheSleep is claim 3, and the assertion
// this file was written for.
//
// The contract says Now() returns "the pre-sleep time plus 5 seconds" -- not
// the time the workflow happened to wake up. The two are indistinguishable on
// an idle machine and diverge under load, which is exactly when a wall-clock
// implementation would do damage and exactly when nobody is looking.
//
// So: exact arithmetic, not a tolerance. A tolerance wide enough to absorb
// scheduling delay is wide enough to absorb the defect.
func TestASleepAdvancesTheClockByExactlyTheSleep(t *testing.T) {
	const sleepMs = 500
	c := runClock(t, sleepMs)

	advanced := c.T3 - c.T2
	if advanced == sleepMs {
		return
	}
	if advanced > sleepMs {
		t.Errorf("a %dms sleep advanced the durable clock by %dms (t2=%d t3=%d).\n"+
			"The excess %dms is wake-up latency, which means Now() is being set from "+
			"the wall clock at resume rather than from pre-sleep + duration. Two "+
			"replays of one history would then disagree.",
			sleepMs, advanced, c.T2, c.T3, advanced-sleepMs)
		return
	}
	t.Errorf("a %dms sleep advanced the durable clock by only %dms (t2=%d t3=%d)",
		sleepMs, advanced, c.T2, c.T3)
}

// TestTheClockCurrentlyGoesBackwardsOnTheFirstEvent pins a defect, so the port
// notices when it is fixed. cleat-team/cleat#944.
//
// This began as TestTheClockNeverGoesBackwards -- the weakest assertion in the
// file and the one expected to survive any redesign of the other two. It failed:
//
//	the durable clock went backwards across t1 -> t2 (durable call):
//	1788833377874 -> 1788833377862 (-12ms)
//
// Two clock domains feed one value. Now() before any event is the workflow
// row's created_at (the DATABASE clock, engine/engine.go:74); the first
// recorded event's timestamp is the worker's time.Now()
// (engine/lifecycle.go:148). Nothing reconciles them, so the step between them
// is the offset between two machines' clocks, in whichever direction they
// happen to differ. Six runs of eight were negative, by up to 26ms.
//
// Inverted rather than skipped: the assertion is one line, and a skip would
// leave the two claims that DO hold -- +0 across CPU work, +200 for a 200ms
// sleep -- without the monotonicity check that gives them context.
func TestTheClockCurrentlyGoesBackwardsOnTheFirstEvent(t *testing.T) {
	// The step across the durable call is the one that mixes domains. Sampled
	// several times because the offset is a clock difference, not a constant,
	// and a single run can land either side of zero.
	const runs = 5
	var negatives int
	var worst int64
	for i := 0; i < runs; i++ {
		c := runClock(t, 200)

		// These two must hold on every run regardless. They are the reason the
		// contract is worth anything, and #944 does not touch them.
		if c.T1 != c.T0 {
			t.Errorf("run %d: Now() advanced %dms across CPU work", i, c.T1-c.T0)
		}
		if c.T3-c.T2 != 200 {
			t.Errorf("run %d: a 200ms sleep advanced the clock %dms", i, c.T3-c.T2)
		}

		if d := c.T2 - c.T1; d < 0 {
			negatives++
			if d < worst {
				worst = d
			}
		}
	}

	if negatives == 0 {
		t.Errorf("cleat#944 appears to be FIXED: the durable clock did not go backwards "+
			"across the durable call in %d runs. Rename this test back to "+
			"TestTheClockNeverGoesBackwards and assert monotonicity across all three "+
			"steps.", runs)
		return
	}
	t.Logf("cleat#944 still present: the durable clock went backwards on %d of %d runs, "+
		"worst %dms. Now() is seeded from the database's created_at and then set from "+
		"the worker's time.Now(); the step is the offset between them.",
		negatives, runs, worst)
}

// TestTwoSleepsAccumulate — a single sleep could pass every assertion above by
// returning a constant. Two sleeps of different lengths in separate runs must
// advance the clock by different, correct amounts.
func TestTwoSleepsAccumulate(t *testing.T) {
	short := runClock(t, 200)
	long := runClock(t, 900)

	shortAdv := short.T3 - short.T2
	longAdv := long.T3 - long.T2
	if longAdv-shortAdv != 700 {
		t.Errorf("a 200ms sleep advanced the clock %dms and a 900ms sleep %dms; "+
			"the difference is %dms, want 700ms", shortAdv, longAdv, longAdv-shortAdv)
	}
}
