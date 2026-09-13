// Package main observes a workflow it did not spawn, for the
// test_retrieve_workflow_in_workflow port.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleObserveRun reads the status of an ARBITRARY run from inside a workflow.
//
// Upstream's test_retrieve_workflow_in_workflow calls retrieve_workflow(id) on
// a workflow the caller did not start. The port work-list classed that case
// "needs something cleat lacks", on the basis that cleat_poll_child and
// cleat_await_child are the only guest-side cross-workflow reads and are
// children-only. That basis is wrong: PollChild passes the run id straight to
// GetChildResult, whose query is `WHERE id = ?` with no parentage predicate in
// any of the three dialects, and the ABI binding does not filter either. A
// store-level probe returned an unrelated workflow's full result body on
// postgres, mysql and mssql alike. Recorded on cleat#1120.
//
// So the capability upstream asserts EXISTS -- it is only misnamed. The `child`
// in poll_child describes the common case, not a restriction.
//
// TWO PARAMETERS, not one. An entry point whose only parameter is a string
// receives the entire input JSON rather than the field of that name
// (wasm/exports.go), so a lone runID would arrive as `{"runID":"..."}` and
// never match a row. tag makes the binding by-name and labels the run.
func HandleObserveRun(h cleat.HostCalls, runID string, tag string) (string, error) {
	h.DurableLog("observe " + tag + ": polling " + runID)

	status, result, err := h.PollChild(runID)
	if err != nil {
		return fmt.Sprintf(`{"tag":%q,"outcome":"error","error":%q}`,
			tag, fmt.Sprintf("%v", err)), nil
	}
	return fmt.Sprintf(`{"tag":%q,"outcome":"observed","status":%q,"result":%s}`,
		tag, status, jsonOrString(result)), nil
}

// jsonOrString keeps the observed result embeddable: PollChild hands back the
// child's result verbatim, which is itself JSON, but an empty string is not.
func jsonOrString(s string) string {
	if s == "" {
		return `""`
	}
	return s
}
