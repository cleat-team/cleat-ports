// Package tests drives a running cleat worker over HTTP.
//
// This file is a near-copy of ports/samples-go/tests/harness_test.go, and the
// duplication is deliberate for the reason that file gives: repeating the
// expensive-to-learn parts of the API as executable code, rather than as a
// comment pointing at another port, means a change to the API breaks both
// ports rather than silently invalidating a reference.
//
// What is NOT duplicated is any import of cleat. See ../go.mod: this port has
// backend-contract cases whose tempting analogue is cleat's store API, and
// keeping the dependency set empty is what stops this port becoming a unit
// test of engine internals wearing a port's name.
package tests

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var (
	apiBase    string
	apiKey     string
	fixtureURL string
	repoRoot   string
)

// TestMain reads the environment scripts/run-port.sh sets and fails loudly if
// it is absent, rather than skipping.
//
// Skipping is the wrong default here and the reason is on the record: the DBOS
// port once reported green for its whole existence because a DSN pointed at a
// service container with no published port, so every database subtest skipped.
// A port that cannot reach its worker has not passed; it has not run.
func TestMain(m *testing.M) {
	apiBase = strings.TrimRight(os.Getenv("CLEAT_PORTS_API"), "/")
	apiKey = os.Getenv("CLEAT_PORTS_API_KEY")
	fixtureURL = strings.TrimRight(os.Getenv("CLEAT_PORTS_FIXTURE_URL"), "/")

	// `go test -list` must work without a database. The count it prints is
	// what ../README.md's status line is derived from, and a status line whose
	// derivation only runs inside the harness is one nobody will re-run.
	for _, arg := range os.Args[1:] {
		if strings.HasPrefix(arg, "-test.list") {
			os.Exit(m.Run())
		}
	}

	var missing []string
	for _, v := range []string{"CLEAT_PORTS_API", "CLEAT_PORTS_API_KEY", "CLEAT_PORTS_DSN"} {
		if os.Getenv(v) == "" {
			missing = append(missing, v)
		}
	}
	if len(missing) > 0 {
		fmt.Fprintf(os.Stderr,
			"durabletask-go: %s unset -- run this port via `make port PORT=durabletask-go` from the\n"+
				"repository root, which starts PostgreSQL, the worker and the fixture service.\n",
			strings.Join(missing, ", "))
		os.Exit(2)
	}
	if fixtureURL == "" {
		fixtureURL = "http://127.0.0.1:8098"
	}

	out, err := exec.Command("git", "rev-parse", "--show-toplevel").Output()
	if err != nil {
		fmt.Fprintf(os.Stderr, "durabletask-go: cannot locate the repository root: %v\n", err)
		os.Exit(2)
	}
	repoRoot = strings.TrimSpace(string(out))

	os.Exit(m.Run())
}

// ---- the client ----

type response struct {
	Status int
	Body   map[string]any
	Raw    string
}

// call is deliberately not a wrapper that fails the test on a non-2xx status.
// Several assertions in this port are ABOUT the status code -- a refused start
// is the behaviour under test, not an error -- and a client that treated 409 as
// a failure would make the interesting case the awkward one to write.
func call(t *testing.T, method, path string, body any, headers map[string]string) response {
	t.Helper()
	var rdr io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshalling request body: %v", err)
		}
		rdr = bytes.NewReader(raw)
	}
	req, err := http.NewRequest(method, apiBase+path, rdr)
	if err != nil {
		t.Fatalf("building %s %s: %v", method, path, err)
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	out := response{Status: resp.StatusCode, Raw: string(raw), Body: map[string]any{}}
	if len(raw) > 0 {
		_ = json.Unmarshal(raw, &out.Body)
	}
	return out
}

// start launches a workflow.
//
// `input` must be a map keyed by the EXACT Go parameter name, camelCase
// included: Handle(h, intervalMs int) takes {"intervalMs": 400}. A mis-cased
// key binds nothing and the parameter keeps its zero value, silently -- the
// DBOS port ran a whole suite that way once, and every assertion still held,
// for weaker reasons than it claimed.
func start(t *testing.T, name string, input map[string]any) response {
	t.Helper()
	return call(t, http.MethodPost, "/api/workflows/"+name+"/start",
		map[string]any{"input": input}, nil)
}

func startedRunID(t *testing.T, r response) string {
	t.Helper()
	if r.Status != http.StatusOK && r.Status != http.StatusCreated && r.Status != http.StatusAccepted {
		t.Fatalf("start answered %d: %s", r.Status, r.Raw)
	}
	for _, k := range []string{"run_id", "id", "workflow_id", "instance_id"} {
		if v, ok := r.Body[k].(string); ok && v != "" {
			return v
		}
	}
	t.Fatalf("start answered %d with no run id: %s", r.Status, r.Raw)
	return ""
}

// awaitTerminal polls until the run stops moving.
//
// The four terminal statuses are listed rather than "not running": a status
// this port has not seen before should hang and report the status it is stuck
// on, not be silently treated as finished.
// terminalStatuses are the statuses a run can settle in, taken from the engine
// rather than assumed: cmd/cleat-worker/server.go's isTerminalStatus.
//
// "dead_lettered" was missing from both readers below, so a dead-lettered run
// -- settled, and the entire subject of the dead-letter tests -- satisfied
// neither. "cancelled" was present in both and is NOT a workflow status: the
// engine never writes it, the cancel endpoint returns
// {"status":"cancellation_requested"} as an API field, and engine/errors.go's
// "cancelled" is an ErrorCode. The Python port says so in its own
// test_cancellation.py docstring, "There is no cancelled terminal status".
//
// Those are one defect. Four names read as an enumeration of "the ways a run
// ends", so nobody checked it against the engine -- and one of the four was
// fictional while a real one was absent.
//
// "terminating" is excluded, and the two readers below want that for OPPOSITE
// reasons, which is why this is a shared list and not a shared predicate:
// awaitTerminal must not return it because the defer phase is still running
// and the final status is not yet written, while isRunning must report it as
// running for exactly the same fact.
var terminalStatuses = map[string]bool{
	"done":          true,
	"failed":        true,
	"terminated":    true,
	"dead_lettered": true,
}

func awaitTerminal(t *testing.T, runID string, timeout time.Duration) map[string]any {
	t.Helper()
	deadline := time.Now().Add(timeout)
	var last map[string]any
	for time.Now().Before(deadline) {
		r := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil)
		last = r.Body
		if st, _ := last["status"].(string); terminalStatuses[st] {
			return last
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("run %s did not reach a terminal status within %s; last status %v",
		runID, timeout, last["status"])
	return nil
}

// queryState reads one published query key from a run.
//
// The value has to be readable while the run is SUSPENDED, which is the case
// the endpoint exists for and the case cleat#844 got wrong: query_state was
// written only on the 'done' and 'failed' branches, so a value reached the
// database only once the run had finished and its result was available anyway.
func queryState(t *testing.T, runID, key string) (int, string) {
	t.Helper()
	r := call(t, http.MethodGet, "/api/workflows/"+runID+"/query?key="+key, nil, nil)
	v, _ := r.Body["value"].(string)
	return r.Status, v
}

// pollQueryState waits for a key to carry a value.
//
// Needed because the interesting value is published mid-run: a caller that
// waits for the run to finish has already missed it, and in this port the runs
// whose query state matters are the ones deliberately closed before they can
// return anything.
func pollQueryState(t *testing.T, runID, key string, timeout time.Duration) string {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, v := queryState(t, runID, key); v != "" {
			return v
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("run %s never published query key %q within %s", runID, key, timeout)
	return ""
}

// dialect reports which database the suite is running against.
//
// Needed by exactly one assertion, and that is the point: cleat#936 is a
// divergence, so the test cannot assert a single behaviour without being wrong
// on one dialect. A test that only ever runs on PostgreSQL would have called
// the MySQL behaviour a regression, and one that only ran on MySQL would never
// have seen the defect at all.
func dialect() string {
	return envOr("CLEAT_PORTS_DIALECT", "postgres")
}

// ---- the fixture service ----

// fixtureCalls returns the operations a key saw, in arrival order, as
// "service.operation" strings. This is the only direct evidence of WHICH calls
// happened and in what order; a run's own result says only that it failed.
func fixtureCalls(t *testing.T, key string) []string {
	t.Helper()
	resp, err := http.Get(fixtureURL + "/log/" + key)
	if err != nil {
		t.Fatalf("reading the fixture call log for %q: %v", key, err)
	}
	defer resp.Body.Close()
	var out struct {
		Calls []string `json:"calls"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("decoding the fixture call log for %q: %v", key, err)
	}
	return out.Calls
}

// waitForCall blocks until the fixture has seen `op` under `key`.
//
// This exists so a precondition can be OBSERVED rather than assumed. The
// child-workflow tests all depend on the child being genuinely mid-flight when
// its parent closes, and the first version of them asserted that by checking
// the call log at parent-close time -- which is a race, not a check: the child
// is scheduled independently, and a parent that finishes in 1.5s can easily
// beat its child's first call.
//
// Deliberately not a fixed sleep. A margin wide enough to "usually" work is
// the defect ports#30 was opened for: 8x on paper and 0x in practice.
func waitForCall(t *testing.T, key, op string, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	var last []string
	for time.Now().Before(deadline) {
		last = fixtureCalls(t, key)
		for _, c := range last {
			if c == op {
				return
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("the fixture never saw %q under key %q within %s; it saw %v",
		op, key, timeout, last)
}

// isRunning reports whether a run has not yet reached a terminal status.
func isRunning(t *testing.T, runID string) bool {
	t.Helper()
	r := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil)
	st, _ := r.Body["status"].(string)
	return !terminalStatuses[st]
}

// signal delivers a signal over HTTP.
//
// The body field is `signal_name`, not `name`. `name` is a 400 saying
// "signal_name is required", which is obvious once seen and invisible before.
func signal(t *testing.T, runID, signalName, payload string) response {
	t.Helper()
	return call(t, http.MethodPost, "/api/workflows/"+runID+"/signal",
		map[string]any{"signal_name": signalName, "payload": payload}, nil)
}

// awaitQueryState waits until a key holds an expected value.
//
// Distinct from pollQueryState, which waits for ANY value: several assertions
// here need to know the workflow has reached a particular phase before the
// test does something to it, and "non-empty" would be satisfied by the
// previous phase.
func awaitQueryState(t *testing.T, runID, key, want string, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	var last string
	for time.Now().Before(deadline) {
		_, last = queryState(t, runID, key)
		if last == want {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("run %s never reached %s=%q within %s; last value %q",
		runID, key, want, timeout, last)
}

// ---- deployment ----

// deploy builds one workflow package to WASM and deploys it under a name.
//
// deploy-workflow, not `cleat deploy`: the CLI's DB-touching subcommands are
// PostgreSQL-only by design and refuse a MySQL or SQL Server DSN, so the CLI
// path would work on one dialect and be assumed on the other two.
// unconditionalBuildWarnings are emitted by every WASM build of every workflow,
// including one that makes no host calls at all, so they say nothing about the
// package being built. cleat's generator emits both imports unconditionally --
// wasm/generator.go, "Always include cleat_complete -- the export wrapper calls
// it" -- while wasm/scan.go compares the binary's imports against the
// WORKFLOW's computed closure, which they are never in by construction. Filed
// as cleat#1125.
//
// They are filtered rather than tolerated because the point of surfacing
// warnings is that someone will read them, and a channel that cries wolf twice
// on every build is one nobody reads. That is not hypothetical: README.md
// records a W003 warning that correctly predicted a failure, went unnoticed,
// and was nearly filed as a cleat defect instead.
//
// The suppressed count is reported, so this stays a filter rather than a
// silence -- and when cleat#1125 is fixed the count goes to zero and the filter
// matches nothing, rather than needing to be removed.
var unconditionalBuildWarnings = []string{
	`host function "cleat_complete" imported from WASM env but not in computed closure`,
	`host function "cleat_poll_work" imported from WASM env but not in computed closure`,
}

// reportBuildWarnings surfaces toolchain warnings from a SUCCESSFUL build.
//
// deploy() read stderr only in the failure branch, so a warning on a build that
// succeeded was discarded -- and the toolchain's warnings are predictions of
// failures that arrive later wearing a different name. W003 ("a single string
// parameter receives the ENTIRE input JSON") was emitted, dropped here, and
// resurfaced two layers away as a result stored as `{}`.
//
// t.Logf rather than t.Errorf: some warnings are advisory, and a harness that
// failed on every one would hold the suite hostage to the toolchain's wording.
// t.Logf is printed whenever the test fails and under -v, which puts the
// prediction in front of whoever is reading the failure it predicted.
func reportBuildWarnings(t *testing.T, pkg, stderr string) {
	t.Helper()
	shown, suppressed := buildWarnings(stderr)
	if len(shown) == 0 {
		return
	}
	t.Logf("building %s produced %d toolchain warning(s); %d unconditional ones suppressed (cleat#1125).\n"+
		"These are PREDICTIONS: a warning here usually surfaces later as a wrong RESULT rather than as a build error.\n  %s",
		pkg, len(shown), suppressed, strings.Join(shown, "\n  "))
}

// buildWarnings splits a build's stderr into the warnings worth showing and a
// count of the unconditional ones dropped. Pure, and separate from the logging,
// so it can be tested against REAL captured toolchain output rather than
// against a hand-written imitation of it -- the filter's whole job is to match
// what the toolchain actually emits, and a fixture I wrote myself would agree
// with my belief about that rather than with the toolchain.
func buildWarnings(stderr string) (shown []string, suppressed int) {
	for _, line := range strings.Split(stderr, "\n") {
		line = strings.TrimSpace(line)
		if !strings.Contains(line, "Warning:") {
			continue
		}
		known := false
		for _, u := range unconditionalBuildWarnings {
			if strings.Contains(line, u) {
				known = true
				break
			}
		}
		if known {
			suppressed++
			continue
		}
		shown = append(shown, line)
	}
	return shown, suppressed
}

func deploy(t *testing.T, pkg, workflowName string) string {
	t.Helper()
	outDir := filepath.Join(repoRoot, ".port-results", "wasm", "durabletask-go", pkg)
	pkgDir := filepath.Join(repoRoot, "ports", "durabletask-go", "workflows", pkg)

	built := exec.Command(filepath.Join(repoRoot, "scripts", "build-workflow.sh"), pkgDir, outDir)
	// Captured separately rather than via Output(), which requires Stderr to be
	// nil -- which is why the old code could reach the toolchain's output only
	// through *exec.ExitError, i.e. only when the build FAILED.
	var stdout, stderr bytes.Buffer
	built.Stdout = &stdout
	built.Stderr = &stderr
	if err := built.Run(); err != nil {
		t.Fatalf("building %s failed: %v\n%s", pkg, err, tail(stderr.String(), 2000))
	}
	// Reading STDERR alone is complete here, and that is a property of the
	// wrapper rather than of cleat. scripts/build-workflow.sh line 76 runs the
	// whole `cleat build` invocation with `) >&2`, so cleat's stdout and stderr
	// are MERGED into this stream and the wrapper's own stdout carries nothing
	// but the .wasm path.
	//
	// That matters because cleat splits its warnings across both streams under
	// the identical "  Warning: " prefix: analyzer warnings including W003 go to
	// stdout (cmd/cleat/main.go:322), the orphaned-import warnings to stderr
	// (:506). A consumer invoking `cleat build` DIRECTLY and reading one stream
	// would silently see a subset -- neither stream says the other exists. Filed
	// as cleat#1128.
	//
	// So this capture is correct because of the merge, not because W003 happens
	// to be on stderr. Measured, not assumed: built through the wrapper, stdout
	// was 37 bytes containing only the path and zero "Warning:" lines, while all
	// three warnings arrived on stderr.
	reportBuildWarnings(t, pkg, stderr.String())
	wasm := stdout.Bytes()

	deployed := exec.Command(filepath.Join(repoRoot, "bin", "deploy-workflow"),
		"-db", os.Getenv("CLEAT_PORTS_DSN"),
		"-driver", envOr("CLEAT_PORTS_DIALECT", "postgres"),
		workflowName, strings.TrimSpace(string(wasm)))
	if out, err := deployed.CombinedOutput(); err != nil {
		t.Fatalf("deploying %s as %q failed: %v\n%s", pkg, workflowName, err, tail(string(out), 2000))
	}
	return workflowName
}

// buildOnly compiles a workflow package and returns the toolchain's combined
// output plus whether it succeeded. It does not deploy.
//
// Separate from deploy() because some workflows in this port exist to be
// REFUSED, and deploy() calls t.Fatalf on a build failure -- which is right for
// a workflow under test and exactly wrong for one whose refusal is the subject.
func buildOnly(t *testing.T, pkg string) (string, bool) {
	t.Helper()
	outDir := filepath.Join(repoRoot, ".port-results", "wasm", "durabletask-go", "refused-"+filepath.Base(pkg))
	pkgDir := filepath.Join(repoRoot, "ports", "durabletask-go", "workflows", pkg)
	if _, err := os.Stat(pkgDir); err != nil {
		t.Fatalf("no such workflow package %s: %v", pkg, err)
	}
	out, err := exec.Command(
		filepath.Join(repoRoot, "scripts", "build-workflow.sh"), pkgDir, outDir).CombinedOutput()
	return string(out), err == nil
}

func envOr(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func tail(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return "..." + s[len(s)-n:]
}
