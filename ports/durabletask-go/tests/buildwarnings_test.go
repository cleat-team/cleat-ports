package tests

// The build-warning filter, tested against REAL captured toolchain output.
//
// The fixture below is the verbatim stderr of `scripts/build-workflow.sh` on a
// workflow whose only parameter is a single string -- the W003 shape. It is
// pasted rather than generated because generating it at test time would need
// the WASM toolchain, and the thing under test is a text filter, not a build.
//
// Pasting real output is the point. The filter's job is to match what the
// toolchain actually prints; a fixture written from memory would agree with my
// belief about the wording rather than with the toolchain, and would keep
// agreeing after the wording changed.

import "testing"

const w003BuildStderr = `  Analyzing package cleatports/w003pkg...
  Found 1 functions, 1 entry point(s), 0 in cleat closure.
  Durable leaves: (none)
  Verifying HostCalls threading... OK

  Warning: HandleW003Probe:6: HandleW003Probe is a workflow entry point whose only parameter is a single string, so "marker" receives the ENTIRE input JSON rather than the field of that name. Starting it with {"marker": "value"} binds marker to the literal text {"marker":"value"}. [W003]
    suggestion: If that is what you want -- an opaque payload the workflow parses itself -- nothing needs to change. If you meant to bind one field by name, add a second parameter or take a struct: func(h cleat.HostCalls, marker string, tag string). Struct parameters are unmarshalled from the input JSON and bind by field.

  Generating WASM imports (0 host functions used)... OK
  Generating host adapter... OK
  Generating WASM exports (1 entry point(s))... OK
  Auto-threading: no changes needed
  Build directory: /tmp/w003out
  Compiling WASM module (go/wasip1)...
  Wrote /tmp/w003out/handle_w003_probe.wasm (3.1 MB)
  Embedded metadata: handle_w003_probe.wasm v1 (ABI v1)

  Warning: host function "cleat_complete" imported from WASM env but not in computed closure; either the closure analysis missed a call path or the WASM binary includes unused imports
  Warning: host function "cleat_poll_work" imported from WASM env but not in computed closure; either the closure analysis missed a call path or the WASM binary includes unused imports
`

// The case the whole change exists for: a real warning survives the filter
// while the two unconditional ones are dropped. Before this change the build
// succeeded and ALL THREE lines were discarded, because deploy() read stderr
// only in its failure branch.
func TestARealWarningSurvivesAndTheUnconditionalOnesDoNot(t *testing.T) {
	shown, suppressed := buildWarnings(w003BuildStderr)

	if suppressed != 2 {
		t.Errorf("expected the 2 unconditional warnings to be suppressed, got %d.", suppressed)
	}
	// NOT a canary for cleat#1125/#1126. The input above is a FROZEN capture, so
	// this count stays 2 however cleat changes -- the test cannot see the fix and
	// will not tell anyone the filter has gone dead. Saying so here because the
	// opposite was assumed out loud: a peer expected this case to fail when the
	// generator fix landed, and it will not.
	//
	//
	// The general form, which is not specific to warnings: a guard cannot detect
	// its own obsolescence from a fixture that froze before the change. That
	// applies to every golden file and captured output in this repo, so the
	// obligation is to name the live signal, as below, rather than to trust the
	// fixture to notice.
	// The live signal is in reportBuildWarnings, which reports the suppressed
	// count on real builds. When cleat-version.env's CLEAT_PINNED_REF (currently
	// `develop`, unpinned) picks up the fix, that count drops to 0 on every build
	// and the filter can be deleted. This file is the regression guard for the
	// FILTER, not a detector of its obsolescence.
	if len(shown) != 1 {
		t.Fatalf("expected exactly 1 warning to survive, got %d: %q", len(shown), shown)
	}
	for _, want := range []string{"W003", "HandleW003Probe", "ENTIRE input JSON"} {
		if !contains(shown[0], want) {
			t.Errorf("the surviving warning does not mention %q, so a reader would not\n"+
				"know which function or which mistake it is about: %q", want, shown[0])
		}
	}
}

// A build with nothing but the unconditional pair must produce NO output at
// all. Without this, a filter that let them through would still "pass" the test
// above -- it only asserts a count -- and every build would log two lines that
// mean nothing, which is the noise this change exists to remove.
func TestACleanBuildLogsNothing(t *testing.T) {
	clean := `  Compiling WASM module (go/wasip1)...
  Wrote handle_x.wasm (4.6 MB)

  Warning: host function "cleat_complete" imported from WASM env but not in computed closure; either the closure analysis missed a call path or the WASM binary includes unused imports
  Warning: host function "cleat_poll_work" imported from WASM env but not in computed closure; either the closure analysis missed a call path or the WASM binary includes unused imports`

	shown, suppressed := buildWarnings(clean)
	if len(shown) != 0 {
		t.Errorf("a build with only the unconditional warnings must log nothing, got %q", shown)
	}
	if suppressed != 2 {
		t.Errorf("expected 2 suppressed, got %d", suppressed)
	}
}

// Output with no warnings at all must not be reported as a warning-free build
// by accident -- e.g. by a filter that matched every line.
func TestOrdinaryBuildChatterIsNotAWarning(t *testing.T) {
	shown, suppressed := buildWarnings("  Analyzing package cleatports/x...\n  Durable leaves: (none)\n  Wrote x.wasm")
	if len(shown) != 0 || suppressed != 0 {
		t.Errorf("plain build chatter was classified as warnings: shown=%q suppressed=%d", shown, suppressed)
	}
}

func contains(s, sub string) bool {
	return len(sub) == 0 || (len(s) >= len(sub) && indexOf(s, sub) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
