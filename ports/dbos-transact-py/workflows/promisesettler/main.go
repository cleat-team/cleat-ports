// Package main is the child workflow that settles a promise its parent created.
package main

import "github.com/cleat-team/cleat/cleat"

// HandleSettle resolves or rejects a promise it did not create.
//
// A promise has to be settled from somewhere other than the workflow waiting on
// it -- a workflow that awaited its own promise would wait forever -- so this
// runs as a child and settles by id.
//
// h.ResolvePromise and h.RejectPromise were unreachable from a Go workflow
// until cleat#806. This is the first Go code that can settle a promise at all.
//
// The parameter names are exact: arguments bind by Go parameter name, so
// `promiseId` is not interchangeable with `promiseid` or `promise_id`.
func HandleSettle(h cleat.HostCalls, promiseId string, mode string) (string, error) {
	if mode == "reject" {
		if err := h.RejectPromise(promiseId, "rejected by the settler"); err != nil {
			return "", err
		}
		return `{"settled":"rejected"}`, nil
	}

	if err := h.ResolvePromise(promiseId, `{"value":"settled"}`); err != nil {
		return "", err
	}
	return `{"settled":"resolved"}`, nil
}
