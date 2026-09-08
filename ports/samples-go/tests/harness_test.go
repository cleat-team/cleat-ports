// Package tests drives a running cleat worker over HTTP.
//
// The DBOS port's equivalent is tests/conftest.py, and this file deliberately
// repeats the parts of it that were expensive to learn -- which route prefix
// each sub-resource lives under, that the idempotency key is a header while
// priority is a body field, that entry-point arguments bind by the EXACT Go
// parameter name. Repeating them as executable code rather than as a comment
// pointing at the other port means a change to the API breaks both.
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
			"samples-go: %s unset -- run this port via `make port PORT=samples-go` from the\n"+
				"repository root, which starts PostgreSQL, the worker and the fixture service.\n",
			strings.Join(missing, ", "))
		os.Exit(2)
	}
	if fixtureURL == "" {
		fixtureURL = "http://127.0.0.1:8098"
	}

	out, err := exec.Command("git", "rev-parse", "--show-toplevel").Output()
	if err != nil {
		fmt.Fprintf(os.Stderr, "samples-go: cannot locate the repository root: %v\n", err)
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
func awaitTerminal(t *testing.T, runID string, timeout time.Duration) map[string]any {
	t.Helper()
	deadline := time.Now().Add(timeout)
	var last map[string]any
	for time.Now().Before(deadline) {
		r := call(t, http.MethodGet, "/api/workflows/"+runID, nil, nil)
		last = r.Body
		switch last["status"] {
		case "done", "failed", "terminated", "cancelled":
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
	switch r.Body["status"] {
	case "done", "failed", "terminated", "cancelled":
		return false
	}
	return true
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
func deploy(t *testing.T, pkg, workflowName string) string {
	t.Helper()
	outDir := filepath.Join(repoRoot, ".port-results", "wasm", "samples-go", pkg)
	pkgDir := filepath.Join(repoRoot, "ports", "samples-go", "workflows", pkg)

	built := exec.Command(filepath.Join(repoRoot, "scripts", "build-workflow.sh"), pkgDir, outDir)
	wasm, err := built.Output()
	if err != nil {
		stderr := ""
		var ee *exec.ExitError
		if ok := asExitError(err, &ee); ok {
			stderr = tail(string(ee.Stderr), 2000)
		}
		t.Fatalf("building %s failed: %v\n%s", pkg, err, stderr)
	}

	deployed := exec.Command(filepath.Join(repoRoot, "bin", "deploy-workflow"),
		"-db", os.Getenv("CLEAT_PORTS_DSN"),
		"-driver", envOr("CLEAT_PORTS_DIALECT", "postgres"),
		workflowName, strings.TrimSpace(string(wasm)))
	if out, err := deployed.CombinedOutput(); err != nil {
		t.Fatalf("deploying %s as %q failed: %v\n%s", pkg, workflowName, err, tail(string(out), 2000))
	}
	return workflowName
}

func asExitError(err error, target **exec.ExitError) bool {
	ee, ok := err.(*exec.ExitError)
	if ok {
		*target = ee
	}
	return ok
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
