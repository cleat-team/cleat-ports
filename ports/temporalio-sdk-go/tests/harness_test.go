// Package tests drives a running cleat worker over HTTP.
//
// The client below is a trimmed near-copy of
// ports/durabletask-go/tests/harness_test.go, and the duplication is
// deliberate for the reason that file gives: repeating the expensive-to-learn
// parts of the API as executable code, rather than as a comment pointing at
// another port, means a change to the API breaks both ports rather than
// silently invalidating a reference.
//
// Trimmed, not copied whole, and the trim has moved once. The schedule cases
// start nothing, so this file carried no workflow helpers at all; the
// duplicate-start cases do start workflows, so build/deploy/poll are here now.
// The fixture-service helpers are still absent, because nothing in this port
// makes a durable call -- and carrying them unused would assert, wrongly, that
// this port has been built to drive the fixture and has simply not done so.
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
	apiBase  string
	apiKey   string
	repoRoot string
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
			"temporalio-sdk-go: %s unset -- run this port via `make port PORT=temporalio-sdk-go`\n"+
				"from the repository root, which starts PostgreSQL and the worker.\n",
			strings.Join(missing, ", "))
		os.Exit(2)
	}

	// Needed by deploy(): the build wrapper, the workflow packages and the
	// deploy tool are all addressed from the repository root, and `go test`
	// runs with the cwd set to the package under test.
	out, err := exec.Command("git", "rev-parse", "--show-toplevel").Output()
	if err != nil {
		fmt.Fprintf(os.Stderr, "temporalio-sdk-go: cannot locate the repository root: %v\n", err)
		os.Exit(2)
	}
	repoRoot = strings.TrimSpace(string(out))

	os.Exit(m.Run())
}

type response struct {
	Status int
	Body   map[string]any
	Raw    string
}

// call is deliberately not a wrapper that fails the test on a non-2xx status.
// Several assertions in this port are ABOUT the status code -- a refused
// duplicate create is the behaviour under test, not an error -- and a client
// that treated 409 as a failure would make the interesting case the awkward one
// to write.
//
// `headers` carries request headers the API reads as INPUT rather than as
// transport: `Idempotency-Key` is one, and cmd/cleat-worker/server.go reads it
// with a bare r.Header.Get and no trimming, so the spelling and the exact bytes
// are part of the contract rather than a detail of this client.
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

// ---- schedules ----

// farFutureCron never fires inside a test run: 03:00 on the 1st of January.
//
// This is what lets these cases name a def_name that need not exist. Both
// assertions are about the schedule ROW -- refused-or-not, and what a policy
// field reads back as -- and neither needs the schedule to start anything. A
// cron that could fire would drag the workflow definition, the WASM build and
// the fixture service into a test that is about none of them.
//
// Said explicitly because the weaker reading is available: this is NOT a claim
// that cleat accepts schedules pointing at definitions that do not exist as a
// GOOD thing. It accepts them, that is a separate question, and nothing here
// asserts either way.
const farFutureCron = "0 3 1 1 *"

type schedule struct {
	Name          string `json:"name"`
	DefName       string `json:"def_name"`
	Cron          string `json:"cron_expression"`
	Enabled       bool   `json:"enabled"`
	MisfirePolicy string `json:"misfire_policy"`
	CatchUpLimit  int    `json:"catch_up_limit"`
	OverlapPolicy string `json:"overlap_policy"`
	Timezone      string `json:"timezone"`
}

// createSchedule posts one schedule. extra carries fields the caller wants to
// set explicitly, which is the whole point of the catch_up_limit case: an
// OMITTED field and a field set to its zero value are different requests, and
// a helper with an int parameter cannot express the difference.
func createSchedule(t *testing.T, name, defName, cron string, extra map[string]any) response {
	t.Helper()
	body := map[string]any{
		"name":        name,
		"cron":        cron,
		"def_name":    defName,
		"entry_point": "main",
	}
	for k, v := range extra {
		body[k] = v
	}
	return call(t, http.MethodPost, "/api/schedules", body, nil)
}

func deleteSchedule(t *testing.T, name string) response {
	t.Helper()
	return call(t, http.MethodDelete, "/api/schedules/"+name, nil, nil)
}

// scheduleNamed returns the one schedule with this name, or nil.
//
// There is no single-schedule GET in cleat -- the routes are create, list,
// enable, disable and delete -- so a "describe" is a list read filtered by
// name. That is stated here rather than in each test, because it is the fact
// that decides most of what is portable from upstream's schedule cases
// (docs/temporalio-sdk-go-schedules-survey.md).
func scheduleNamed(t *testing.T, name string) *schedule {
	t.Helper()
	r := call(t, http.MethodGet, "/api/schedules", nil, nil)
	if r.Status != http.StatusOK {
		t.Fatalf("listing schedules answered %d: %s", r.Status, r.Raw)
	}
	var all []schedule
	if err := json.Unmarshal([]byte(r.Raw), &all); err != nil {
		t.Fatalf("decoding the schedule list: %v (raw: %s)", err, r.Raw)
	}
	for i := range all {
		if all[i].Name == name {
			return &all[i]
		}
	}
	return nil
}

// cleanupSchedule deletes a schedule and does NOT assert the delete succeeded.
//
// Deliberate, and it is the one place this port knowingly accepts a silent
// no-op: cleat#1297 records that DELETE answers 200 for a name that does not
// exist, so a cleanup assertion here could not distinguish "removed" from
// "there was nothing to remove". Asserting removal is the subject of a test,
// not of a defer.
func cleanupSchedule(t *testing.T, name string) {
	t.Helper()
	t.Cleanup(func() { deleteSchedule(t, name) })
}

// setScheduleEnabled flips a schedule's enabled flag. The trailing `nil` is the
// headers argument call() grew for `Idempotency-Key`; this route needs none.
func setScheduleEnabled(t *testing.T, name string, enabled bool) response {
	t.Helper()
	verb := "disable"
	if enabled {
		verb = "enable"
	}
	return call(t, http.MethodPost, "/api/schedules/"+name+"/"+verb, nil, nil)
}

// ---- workflows ----

// deploy builds a workflow package to WASM against the cleat checkout under
// test and registers it under `workflowName`.
//
// Trimmed from ports/durabletask-go/tests/harness_test.go's deploy(): the
// build-warning reporting is not carried, because this port has one workflow
// package and cleat#1125/#1128 are already pinned by two other ports. What IS
// carried is capturing stdout and stderr separately -- scripts/build-workflow.sh
// echoes the .wasm path on stdout and merges everything else onto stderr, so
// combining them would put toolchain prose into the path.
func deploy(t *testing.T, pkg, workflowName string) string {
	t.Helper()
	outDir := filepath.Join(repoRoot, ".port-results", "wasm", "temporalio-sdk-go", pkg)
	pkgDir := filepath.Join(repoRoot, "ports", "temporalio-sdk-go", "workflows", pkg)

	built := exec.Command(filepath.Join(repoRoot, "scripts", "build-workflow.sh"), pkgDir, outDir)
	var stdout, stderr bytes.Buffer
	built.Stdout = &stdout
	built.Stderr = &stderr
	if err := built.Run(); err != nil {
		t.Fatalf("building %s failed: %v\n%s", pkg, err, tail(stderr.String(), 2000))
	}

	deployed := exec.Command(filepath.Join(repoRoot, "bin", "deploy-workflow"),
		"-db", os.Getenv("CLEAT_PORTS_DSN"),
		"-driver", envOr("CLEAT_PORTS_DIALECT", "postgres"),
		workflowName, strings.TrimSpace(stdout.String()))
	if out, err := deployed.CombinedOutput(); err != nil {
		t.Fatalf("deploying %s as %q failed: %v\n%s", pkg, workflowName, err, tail(string(out), 2000))
	}
	return workflowName
}

// start launches a workflow, optionally under an idempotency key.
//
// `input` must be keyed by the EXACT Go parameter name, camelCase included:
// HandleReuse(h, marker string, sleepMs int, fail int) takes
// {"marker": ..., "sleepMs": ..., "fail": ...}. A mis-cased key binds nothing
// and the parameter keeps its zero value, silently -- the DBOS port ran a whole
// suite that way once, and every assertion still held, for weaker reasons than
// it claimed.
//
// In this port the mis-cased-key hazard has teeth the other ports do not face:
// `sleepMs` is what keeps the first run RUNNING while the duplicate start is
// sent. A dropped `sleepMs` would make every run finish instantly, and the DONE
// and FAILED arms would then pass having established nothing about a live
// winner.
//
// What stops that being silent is the unfinished-winner arm, and only because
// it checks the RUN ROW -- `completed_at` empty, `next_wake_at` far enough
// after `started_at` -- before asking the question. Measured: without that
// guard, mis-casing the key to `sleepms` left all three cases green, because
// cleat's `ready` covers "parked in a durable sleep" and "not claimed yet"
// alike and a 50ms run is indistinguishable from a 20-second one.
//
// Said here because the arms look independent and are not: deleting the
// unfinished case, or weakening its guard, leaves the remaining two vacuous
// rather than merely fewer.
func start(t *testing.T, name, idempotencyKey string, input map[string]any) response {
	t.Helper()
	var headers map[string]string
	if idempotencyKey != "" {
		headers = map[string]string{"Idempotency-Key": idempotencyKey}
	}
	return call(t, http.MethodPost, "/api/workflows/"+name+"/start",
		map[string]any{"input": input}, headers)
}

func startedRunID(t *testing.T, r response) string {
	t.Helper()
	if r.Status != http.StatusOK && r.Status != http.StatusCreated && r.Status != http.StatusAccepted {
		t.Fatalf("start answered %d: %s", r.Status, r.Raw)
	}
	for _, k := range []string{"id", "workflow_id", "run_id"} {
		if v, ok := r.Body[k].(string); ok && v != "" {
			return v
		}
	}
	t.Fatalf("start answered %d with no run id: %s", r.Status, r.Raw)
	return ""
}

// terminalStatuses are the statuses a run can settle in, taken from the engine
// rather than assumed: cmd/cleat-worker/server.go's isTerminalStatus.
//
// Copied WITH its history from ports/durabletask-go, because the history is the
// warning: that port's list once read done/failed/terminated/cancelled, which
// looks like a complete enumeration of "the ways a run ends" and is wrong twice
// -- "cancelled" is not a workflow status (the engine never writes it; it is an
// API field and an ErrorCode) and "dead_lettered", which is a real terminal
// status, was missing. A plausible-looking list is how that survived.
//
// "terminating" is excluded: the defer phase is still running and the final
// status is not yet written.
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
