// Package tests drives a running cleat worker over HTTP.
//
// The client below is a trimmed near-copy of
// ports/durabletask-go/tests/harness_test.go, and the duplication is
// deliberate for the reason that file gives: repeating the expensive-to-learn
// parts of the API as executable code, rather than as a comment pointing at
// another port, means a change to the API breaks both ports rather than
// silently invalidating a reference.
//
// Trimmed, not copied whole. The workflow-start, terminal-poll and fixture
// helpers are absent because nothing here starts a workflow -- see ../go.mod.
// Carrying them unused would assert, wrongly, that this port has been built to
// run workflows and has simply not done so yet.
package tests

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

var (
	apiBase string
	apiKey  string
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
	os.Exit(m.Run())
}

type response struct {
	Status int
	Body   map[string]any
	Raw    string
}

// call is deliberately not a wrapper that fails the test on a non-2xx status.
// Both assertions in this port are ABOUT the status code -- a refused duplicate
// create is the behaviour under test, not an error -- and a client that treated
// 409 as a failure would make the interesting case the awkward one to write.
func call(t *testing.T, method, path string, body any) response {
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
	return call(t, http.MethodPost, "/api/schedules", body)
}

func deleteSchedule(t *testing.T, name string) response {
	t.Helper()
	return call(t, http.MethodDelete, "/api/schedules/"+name, nil)
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
	r := call(t, http.MethodGet, "/api/schedules", nil)
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

func setScheduleEnabled(t *testing.T, name string, enabled bool) response {
	t.Helper()
	verb := "disable"
	if enabled {
		verb = "enable"
	}
	return call(t, http.MethodPost, "/api/schedules/"+name+"/"+verb, nil)
}
