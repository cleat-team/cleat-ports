package tests

// Not a port of an upstream sample. This came out of reading the route table
// while porting, and it is here because the shape it describes is one Temporal
// does not have.
//
// In Temporal a workflow ID and a workflow TYPE are different things in
// different places: the type is registered on a worker, the ID addresses a run,
// and no API path takes either interchangeably. cleat's routes put both in the
// same path segment and disambiguate on the SUFFIX:
//
//	GET  /api/workflows/{id}/history      run id
//	GET  /api/workflows/{id}/query        run id
//	GET  /api/workflows/{id}/promises     run id
//	GET  /api/workflows/{name}/routing    definition NAME
//	GET  /api/workflows/{name}/tags       definition NAME
//	POST /api/workflows/{name}/start      definition NAME
//
// A caller cannot tell from the URL which kind a segment is, and the two
// namespaces never overlap -- a run id is a UUID and a name is not -- so
// passing the wrong one produces a plausible empty answer rather than an error.

import (
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

// TestARunIdWhereANameBelongsAnswersEmpty pins the hazard.
//
// This is CURRENT BEHAVIOUR and arguably correct on its own terms: an empty
// routing table is the normal state for most definitions, so 200 [] is a fair
// answer to "what rules does this have". What it cannot express is that the
// question was about the wrong kind of thing.
//
// Recorded rather than filed as a defect, because closing it is a decision
// about what an unknown definition name should return -- see ISSUES.md #8. If
// these ever answer 404, that decision has been taken and this test should say
// so rather than be deleted.
func TestARunIdWhereANameBelongsAnswersEmpty(t *testing.T) {
	// A syntactically valid run id. No definition is named this, and none could
	// be -- but the routing and tags endpoints take a NAME here.
	const runIDShaped = "00000000-0000-0000-0000-000000000000"

	routing := call(t, http.MethodGet, "/api/workflows/"+runIDShaped+"/routing", nil, nil)
	if routing.Status != 200 {
		t.Errorf("cleat#900's treatment has reached /routing: a run-id-shaped name "+
			"answered %d rather than 200 %s. If unknown definition names now 404, "+
			"update ISSUES.md #8 -- the decision has been taken.",
			routing.Status, routing.Raw)
	}

	tags := call(t, http.MethodGet, "/api/workflows/"+runIDShaped+"/tags", nil, nil)
	if tags.Status != 200 {
		t.Errorf("a run-id-shaped name answered %d on /tags rather than 200 %s",
			tags.Status, tags.Raw)
	}

	// The point of the test: this is byte-identical to the answer for a real
	// definition that genuinely has no rules and no tags. Nothing distinguishes
	// "you asked about the wrong kind of thing" from "there is nothing here".
	name := call(t, http.MethodGet, "/api/workflows/"+sagaWorkflow(t)+"/routing", nil, nil)
	if strings.TrimSpace(name.Raw) != strings.TrimSpace(routing.Raw) {
		t.Logf("a real definition with no rules answers %q while a run-id-shaped name "+
			"answers %q -- they are now distinguishable, which is the improvement "+
			"ISSUES.md #8 describes", name.Raw, routing.Raw)
	}
}

// TestTheTwoIdentifierKindsAreNotInterchangeable is the control, and it is what
// makes the test above about cleat rather than about a made-up id.
//
// A run-scoped read given a definition NAME must not answer as though the name
// were a run. If it did, the two namespaces would genuinely overlap and the
// observation above would be wrong.
func TestTheTwoIdentifierKindsAreNotInterchangeable(t *testing.T) {
	name := sagaWorkflow(t)

	// A definition name on a RUN-scoped read. Since cleat#935 every run-scoped
	// read 404s for an id that names no run, and a definition name names none.
	r := call(t, http.MethodGet, "/api/workflows/"+name+"/query?key=counter", nil, nil)
	if r.Status != 404 {
		t.Errorf("a definition name on a run-scoped read answered %d: %s\n"+
			"200 would mean the two identifier namespaces overlap, and a caller could "+
			"not tell which kind any path segment wanted", r.Status, r.Raw)
	}

	// And the same name on a DEFINITION-scoped read is a real answer, so the
	// name itself is not the reason for the 404 above.
	d := call(t, http.MethodGet, "/api/workflows/"+name+"/tags", nil, nil)
	if d.Status != 200 {
		t.Fatalf("the same name answered %d on a definition-scoped read: %s", d.Status, d.Raw)
	}
	var tags map[string]int
	if err := json.Unmarshal([]byte(d.Raw), &tags); err != nil {
		t.Errorf("a definition-scoped read did not return a JSON object: %v (%s)", err, d.Raw)
	}
}
