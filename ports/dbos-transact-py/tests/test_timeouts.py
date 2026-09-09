"""Upstream test_queue.py::test_unsetting_timeout — workflow-level deadlines.

Upstream sets a timeout on a run, has that run enqueue two children, and
asserts the child that inherits the parent's deadline is cancelled by it while
the child wrapped in SetWorkflowTimeout(None) survives.

cleat has one workflow timeout and it is `--max-workflow-duration`, a worker
flag applied to every workflow the worker runs. The start API accepts no
timeout field at all, so there is no per-run value to set, nothing for a child
to inherit, and nothing for it to decline. See ISSUES.md 25.
"""
import pytest


@pytest.mark.skip(
    reason="GAP: cleat has no per-run workflow timeout. Upstream sets one at "
           "the call site with SetWorkflowTimeout(2.0) and unsets it for one "
           "child with SetWorkflowTimeout(None); cleat's only workflow "
           "deadline is the --max-workflow-duration worker flag, which "
           "applies to every workflow that worker runs. handleStartWorkflow "
           "accepts input, entry_point, concurrency_key, tenant_id, namespace "
           "and priority -- no timeout. ISSUES.md 25."
)
def test_a_child_can_decline_the_deadline_it_inherits():
    """Upstream test_unsetting_timeout.

    Left in place, skipped, rather than omitted: an absent test is
    indistinguishable from an untried one, and inherited-deadline behaviour is
    among the first things a reader comparing the two systems will look for.

    Not written against `--max-workflow-duration` via
    CLEAT_PORTS_WORKER_EXTRA_FLAGS (ports#70), which can start a worker with a
    deadline: that deadline would apply to every other case sharing the worker,
    and it still could not express the difference between the two children,
    which is the whole assertion. A test that cannot fail for its own reason is
    worse than a skip, because it looks like coverage.
    """
