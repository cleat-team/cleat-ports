// Package main spawns two children by the two different paths, so a test can
// read back what priority each one was given.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleChildPriority starts one child through the no-options path and one
// through ChildWorkflowWithOptions with an explicit Priority, and returns both
// run IDs so the caller can GET each and compare.
//
// TWO CHILDREN FROM ONE PARENT, rather than two parents with one child each,
// because the interesting comparison is against the PARENT'S OWN priority and
// both children have to share it for that to mean anything. The parent is
// started at a deliberately middling priority; if a child inherited, the plain
// child would come back with the parent's number.
//
// WHY THE PLAIN PATH IS THE ONE WORTH PINNING. `cleat/runtime_children.go:22-25`
// documents "Children do NOT inherit the parent's priority", which reads like a
// statement about what does NOT happen and leaves open what does.
// `engine/children.go:16` answers it: the no-options path passes priority as a
// literal 0, and every claim query orders `priority ASC`. So a child started the
// ordinary way is not merely un-inherited, it is given the BEST priority there
// is -- a low-priority parent's children jump ahead of that parent's own peers.
// That is a much stronger claim than the comment makes, and nothing asserted it.
//
// The children are child_leaf, which sleeps and reports its tag. They are not
// awaited: awaiting would make the parent's completion depend on theirs, and
// this workflow is only a vehicle for getting two rows written with known
// provenance. The test reads the children directly.
func HandleChildPriority(h cleat.HostCalls, tag string, childMs int, explicitPriority int) (string, error) {
	plain, err := h.ChildWorkflow("child_leaf",
		fmt.Sprintf(`{"ms":%d,"tag":%q}`, childMs, tag+"-plain"))
	if err != nil {
		return "", fmt.Errorf("spawn plain child: %w", err)
	}

	explicit, err := h.ChildWorkflowWithOptions("child_leaf",
		fmt.Sprintf(`{"ms":%d,"tag":%q}`, childMs, tag+"-explicit"),
		cleat.ChildWorkflowOptions{Priority: explicitPriority})
	if err != nil {
		return "", fmt.Errorf("spawn explicit child: %w", err)
	}

	return fmt.Sprintf(`{"plain":%q,"explicit":%q}`, plain, explicit), nil
}
