"""Upstream test_queue.py::test_queue_executor_id — which worker ran a run.

Upstream treats `executor_id` as a durable property of a run: a completed
workflow still names the executor that originally ran it, and starting the same
workflow id again under a different executor does not overwrite it.

cleat's nearest field is `workflow_instances.assigned_to`, which is a lease
rather than a record. `finalize_workflow_status` fences the terminal write on
`assigned_to = p_worker_id` and sets `assigned_to = NULL` in the same
statement, on every terminal branch, on all three dialects. See ISSUES.md 26.
"""
import pytest


@pytest.mark.skip(
    reason="GAP: cleat keeps no durable record of which worker ran a workflow. "
           "assigned_to is a lease -- finalize_workflow_status clears it on "
           "every terminal branch while fencing the write on it, so the field "
           "that would name the worker is the fence for the write that erases "
           "it. Blank on 185 of 185 terminal runs. ISSUES.md 26."
)
def test_a_completed_run_still_names_the_worker_that_ran_it():
    """Upstream test_queue_executor_id.

    Left in place, skipped, rather than omitted: an absent test is
    indistinguishable from an untried one, and "which worker ran this" is a
    routine question about a failed or slow run.

    Not written against a RUNNING workflow, which would pass: assigned_to does
    hold a real worker id while a run is in flight. That test would assert that
    the lease works, which is not what upstream asserts and would read as
    coverage of a property cleat does not have. Every run worth asking about
    afterwards is one that has already reached a terminal state.
    """
