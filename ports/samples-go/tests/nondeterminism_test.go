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

// TestForbiddenConstructsCurrentlyBuildWhenNothingCallsTheHost pins cleat#949.
//
// Each of these is a construct the analyzer refuses -- when the function
// reaches a host call. None of them does, so all three build and deploy.
//
// Pinned rather than asserted-correct because the correct assertion fails
// today, and a red suite is one people stop reading. When #949 lands this goes
// red and says so.
func TestForbiddenConstructsCurrentlyBuildWhenNothingCallsTheHost(t *testing.T) {
	for _, tc := range []struct {
		pkg, code, why string
	}{
		{"nondeterminism/goroutine", "E001",
			"a goroutine plus a channel: the literal shape of upstream's sample"},
		{"nondeterminism/channel", "E002",
			"channels with no goroutine, so the exemption cannot be attributed to `go`"},
		{"nondeterminism/syncmutex", "E013",
			"a sync primitive with no concurrency at all"},
	} {
		t.Run(tc.pkg, func(t *testing.T) {
			out, ok := buildOnly(t, tc.pkg)
			if !ok {
				if strings.Contains(out, tc.code) {
					t.Errorf("cleat#949 appears to be FIXED: %s is now refused with %s. "+
						"Rewrite this test to assert the refusal and delete the pin.",
						tc.pkg, tc.code)
					return
				}
				t.Fatalf("%s failed to build, but not with %s -- neither the defect nor "+
					"the fix:\n%s", tc.pkg, tc.code, tail(out, 600))
			}
			t.Logf("cleat#949 still present: %s built with no diagnostic (%s). "+
				"The function makes no host call, so it is outside the cleat closure "+
				"and the determinism checks do not run on it.", tc.pkg, tc.why)
		})
	}
}

// TestAHelperEscapesTheCheckEvenInsideAReplayedWorkflow is the case that makes
// cleat#949 worth filing rather than noting.
//
// The entry point calls the host, so it is checked AND it suspends and replays.
// The helper it calls does not, so it is not checked -- while being re-executed
// on every replay, because replay re-runs the workflow function and constrains
// only the results of host calls, not local computation.
//
// Six violations across three codes, and the build is silent.
func TestAHelperEscapesTheCheckEvenInsideAReplayedWorkflow(t *testing.T) {
	out, ok := buildOnly(t, "nondeterminism/helperescape")
	if !ok {
		t.Errorf("cleat#949 appears to be FIXED: a non-deterministic helper outside the "+
			"cleat closure is now reported. Rewrite this test to assert it.\n%s",
			tail(out, 800))
		return
	}
	// The analyzer SEES the helper -- it counts it -- and does not check it.
	// Asserted because "2 functions, 1 in cleat closure" is the entire
	// mechanism, and a build that stopped seeing it would be a different bug
	// wearing this one's result.
	if !strings.Contains(out, "2 functions") || !strings.Contains(out, "1 in cleat closure") {
		t.Errorf("the analyzer no longer reports 2 functions with 1 in the closure, so "+
			"this test may not be measuring cleat#949 any more:\n%s", tail(out, 600))
	}
	t.Logf("cleat#949 still present: a helper with goroutines, channels, close(), " +
		"sync.Mutex and sync.WaitGroup built silently inside a workflow that suspends " +
		"and replays.")
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
