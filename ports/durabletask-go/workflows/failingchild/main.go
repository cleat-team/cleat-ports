// Package main is a child workflow that always fails.
package main

import (
	"errors"

	"github.com/cleat-team/cleat/cleat"
)

// HandleFailingChild fails with a caller-supplied marker in its message.
//
// The marker is what makes the parent's assertion more than "something went
// wrong": upstream asserts the parent's failure details CONTAIN the child's
// message, so the test needs a string that could only have come from here.
func HandleFailingChild(h cleat.HostCalls, marker string, unused int) (string, error) {
	return "", errors.New("child failed: " + marker)
}
