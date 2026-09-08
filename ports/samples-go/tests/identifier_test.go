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
//	GET  /api/workflows/{name}/routing    definition NAME
//	GET  /api/workflows/{name}/tags       definition NAME
//	POST /api/workflows/{name}/start      definition NAME
//
// A caller still cannot tell from the URL which kind a segment wants. What has
// changed is that giving the wrong kind is now an error rather than a plausible
// empty answer: cleat#945 made the name-scoped reads 404 for a name that is not
// a definition, and a run id is never a definition name.

import (
	"encoding/json"
	"net/http"
	"testing"
)

// TestAnUnknownDefinitionNameIs404 was written as a pin and is now an
// assertion, which is the whole argument for writing pins.
//
// It first asserted the opposite: that these answered 200 with an empty
// collection, byte-identical to a real definition with nothing in it. cleat#945
// landed and this went red in the next run, printing what had changed. Third
// time in two days that a deliberate red has been the news.
func TestAnUnknownDefinitionNameIs404(t *testing.T) {
	for _, path := range []string{
		"/api/workflows/no_such_workflow_name/routing",
		"/api/workflows/no_such_workflow_name/tags",
		// A syntactically valid run id, which is never a definition name. This
		// is the identifier-kind confusion specifically, not just an unknown
		// string.
		"/api/workflows/00000000-0000-0000-0000-000000000000/routing",
		"/api/workflows/00000000-0000-0000-0000-000000000000/tags",
	} {
		r := call(t, http.MethodGet, path, nil, nil)
		if r.Status != 404 {
			t.Errorf("%s answered %d: %s\n"+
				"200 with an empty collection would mean a caller cannot tell "+
				"'this definition has no rules' from 'there is no such definition' -- "+
				"and cannot tell either from 'you passed a run id where a name belongs'",
				path, r.Status, r.Raw)
		}
	}
}

// TestAKnownDefinitionWithNothingIsStill200 is the control, and it is the one
// that matters.
//
// An over-broad version of cleat#945 -- 404 whenever the collection comes back
// empty -- passes every assertion above and breaks every caller polling a
// definition that simply has no routing yet. Most definitions have none.
func TestAKnownDefinitionWithNothingIsStill200(t *testing.T) {
	name := sagaWorkflow(t)

	routing := call(t, http.MethodGet, "/api/workflows/"+name+"/routing", nil, nil)
	if routing.Status != 200 {
		t.Errorf("a deployed definition with no routing rules answered %d: %s\n"+
			"An empty routing table is the normal state; this must stay 200.",
			routing.Status, routing.Raw)
	}

	tags := call(t, http.MethodGet, "/api/workflows/"+name+"/tags", nil, nil)
	if tags.Status != 200 {
		t.Fatalf("a deployed definition with no tags answered %d: %s", tags.Status, tags.Raw)
	}
	var out map[string]int
	if err := json.Unmarshal([]byte(tags.Raw), &out); err != nil {
		t.Errorf("a definition-scoped read did not return a JSON object: %v (%s)", err, tags.Raw)
	}
}

// TestTheTwoIdentifierKindsAreNotInterchangeable — a definition name on a
// RUN-scoped read must 404, or the two namespaces would genuinely overlap and
// everything above would be measuring nothing.
func TestTheTwoIdentifierKindsAreNotInterchangeable(t *testing.T) {
	name := sagaWorkflow(t)
	r := call(t, http.MethodGet, "/api/workflows/"+name+"/query?key=counter", nil, nil)
	if r.Status != 404 {
		t.Errorf("a definition name on a run-scoped read answered %d: %s\n"+
			"200 would mean the two identifier namespaces overlap, and a caller could "+
			"not tell which kind any path segment wanted", r.Status, r.Raw)
	}
}

// TestDeletingATagOnAnUnknownDefinitionCurrentlyAnswers200 pins the one path
// cleat#945 deliberately did not change, with the reason recorded so whoever
// decides it argues with the position rather than around it.
//
//	DELETE /api/workflows/no_such_workflow_name/tags/stable -> 200
//
// The case FOR leaving it: DELETE is conventionally idempotent, and removing a
// tag that is not there is a no-op success. Making it 404 changes that.
//
// The case AGAINST: the thing that does not exist here is the DEFINITION, not
// the tag. "The tag was removed" and "there is no such workflow" share one
// response, and a caller who typos the workflow name is told the deletion
// succeeded. cleat#945 has just decided that an unknown definition is a 404 on
// the reads; the writes already 409. This is the last path where an unknown
// definition is silently fine.
//
// Not filed as a defect: idempotency is a real principle and this is a decision
// about which of two conventions wins. Pinned so the decision is visible and so
// the port notices whichever way it goes.
func TestDeletingATagOnAnUnknownDefinitionCurrentlyAnswers200(t *testing.T) {
	r := call(t, http.MethodDelete,
		"/api/workflows/no_such_workflow_name_for_delete/tags/stable", nil, nil)

	switch r.Status {
	case 200:
		t.Logf("current behaviour: DELETE on an unknown definition answers 200. " +
			"Idempotent, and indistinguishable from a successful removal.")
	case 404:
		t.Errorf("DELETE on an unknown definition now answers 404, so the idempotency " +
			"question has been decided the other way. Update this test to assert it " +
			"and record the decision in ISSUES.md #8.")
	default:
		t.Errorf("DELETE on an unknown definition answered %d: %s -- neither convention",
			r.Status, r.Raw)
	}
}
