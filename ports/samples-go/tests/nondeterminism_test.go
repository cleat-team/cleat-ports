package tests

// temporalio/samples-go `goroutine/` and `mutex/` cannot be ported, and that is
// the finding rather than an obstacle to one.
//
// Temporal offers deterministic concurrency INSIDE a workflow: workflow.Go
// schedules goroutines cooperatively, so the sample's fan-out is safe there.
// cleat's model is that workflow code is single-threaded by design, and the
// analyzer refuses the whole family -- goroutines (E001), channels (E002),
// sync primitives (E013).
//
// Writing the port as its own refusal is the only way to express it. Doing so
// found cleat#949: the refusal is conditional on something unrelated to
// determinism.

import (
	"strings"
	"testing"
)

// TestTheRuleIsRealWhenItApplies is the control, and everything else here is
// meaningless without it.
//
// If the analyzer simply did not implement these codes, every "it built"
// assertion below would be equally explained. This fixture is byte-identical to
// nondeterminism/syncmutex except for one h.SetQueryState call.
func TestTheRuleIsRealWhenItApplies(t *testing.T) {
	out, ok := buildOnly(t, "nondeterminism/mutexwithcall")
	if ok {
		t.Fatalf("a sync.Mutex in a function that DOES make a host call was accepted.\n"+
			"cleat#949 would then be understating the problem: the determinism codes "+
			"would not be enforced at all.\n%s", tail(out, 600))
	}
	if !strings.Contains(out, "E013") {
		t.Errorf("the build was refused but not with E013, so it may have failed for an "+
			"unrelated reason:\n%s", tail(out, 600))
	}
}

// TestForbiddenConstructsAreRefusedAtBuildTime is the port of `goroutine/` and
// `mutex/`, finally able to assert what it always meant.
//
// It shipped as a pin -- asserting that these BUILT, because they did -- and
// went red when cleat#949 was fixed. That is the construction working: the
// pin's own message named the issue and said to rewrite it, which is this.
//
// Worth recording how nearly it went wrong. #949 was fixed in two parts. The
// first (#964) seeded the analyzer's walk from durable functions, which caught
// `helperescape` and left `syncmutex` building, because a workflow that makes
// no host call is neither durable nor the callee of anything durable. Measured
// on develop at that point:
//
//	syncmutex       BUILT     codes: none
//	helperescape    REFUSED   E001 E002 E012 E013
//
// So the pin would have gone HALF red. The natural response to a red pin is to
// rewrite it to match the new behaviour -- and doing that here would have
// quietly encoded the remaining defect as expected. #968 added entry points to
// the seed and closed it.
//
// The signal is not "did the pin go red". It is "did every case that should
// have moved, move" -- three fixtures with one moving is a question, not a
// result.
func TestForbiddenConstructsAreRefusedAtBuildTime(t *testing.T) {
	for _, tc := range []struct {
		pkg, code, why string
	}{
		{"nondeterminism/goroutine", "E001",
			"a goroutine plus a channel: the literal shape of upstream's sample"},
		{"nondeterminism/channel", "E002",
			"channels with no goroutine, so the refusal cannot be attributed to `go`"},
		{"nondeterminism/syncmutex", "E013",
			"a sync primitive with no concurrency and NO HOST CALL -- the case #964 " +
				"left open and #968 closed"},
	} {
		t.Run(tc.pkg, func(t *testing.T) {
			out, ok := buildOnly(t, tc.pkg)
			if ok {
				t.Fatalf("%s BUILT. %s.\n"+
					"cleat's determinism model rests on this being refused at build time; "+
					"if it reaches a worker the failure is a checksum mismatch in "+
					"production against a workflow that passed review.", tc.pkg, tc.why)
			}
			if !strings.Contains(out, tc.code) {
				t.Errorf("%s was refused, but not with %s -- so it may have failed for an "+
					"unrelated reason and this test would pass either way.\n%s",
					tc.pkg, tc.code, tail(out, 600))
			}
		})
	}
}

// TestAHelperIsCheckedEvenThoughItMakesNoHostCall is the sharp case of #949,
// now asserted rather than pinned.
//
// The entry point calls the host, so it is checked and it suspends and
// replays. The helper does not, and was invisible -- while being re-executed on
// every replay, because replay re-runs the workflow function and constrains
// only the results of host calls, not local computation.
//
// Six violations across FOUR codes: goroutines (E001), channel send and receive
// (E002), close() (E012, its own code rather than part of E002), sync.Mutex and
// sync.WaitGroup (E013). The grouping is a correction -- this port and #949
// both said three codes until a build reported an E012 nobody had predicted.
func TestAHelperIsCheckedEvenThoughItMakesNoHostCall(t *testing.T) {
	out, ok := buildOnly(t, "nondeterminism/helperescape")
	if ok {
		t.Fatalf("a helper carrying goroutines, channels, close(), sync.Mutex and "+
			"sync.WaitGroup built silently inside a workflow that suspends and "+
			"replays.\n%s", tail(out, 800))
	}
	for _, code := range []string{"E001", "E002", "E012", "E013"} {
		if !strings.Contains(out, code) {
			t.Errorf("the helper's violations should span E001, E002, E012 and E013; "+
				"%s is missing:\n%s", code, tail(out, 800))
		}
	}
}

// TestTheSanctionedAlternativesStillBuild — without this, every assertion above
// passes against a toolchain that refuses nothing at all.
func TestTheSanctionedAlternativesStillBuild(t *testing.T) {
	for _, pkg := range []string{
		"childparent",  // concurrency via child workflows
		"durableclock", // waiting via DurableSleep
	} {
		if out, ok := buildOnly(t, pkg); !ok {
			t.Errorf("%s no longer builds, so the determinism rules now refuse the "+
				"alternative they recommend:\n%s", pkg, tail(out, 600))
		}
	}
}
