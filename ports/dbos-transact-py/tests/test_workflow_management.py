"""The operator API: forcing a stuck run to a terminal state.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream file: `tests/test_workflow_management.py` — cancel, resume, fork, list,
restart. Cleat's operator surface is narrower and differently shaped: there is
no resume or fork, and the equivalent of "get this stuck run out of my queue"
is `force-complete` / `force-fail` under `/api/admin/instances/{id}/`.

This file exists because that surface has produced two defects and had no port
coverage for either:

- **cleat#830** — seven instance and admin routes were registered on a route
  table the binary never served. The endpoints answered the SPA's HTML fallback
  with **200**, so a client saw a web page where it expected JSON. A test that
  only asserted "the request came back" would have passed throughout.
- **cleat#832** — the HTTP status was derived from the error *message* by
  substring, so refusals that should have been 400/404/409 answered 500.

Both are status-code defects, which is why every assertion here pins the exact
status rather than a success/failure class.
"""

import json
import time
import uuid

import pytest


def _claimed_generation(cleat, run_id, timeout=30.0):
    """Wait until the run has been claimed, and return its generation.

    A run is inserted at generation 0 and bumped to 1 when a worker claims it.
    Reading the generation immediately after start therefore races the
    dispatcher, and the operator API rejects a stale generation with a 409 --
    correctly. That 409 is the assertion of another test in this file, so
    letting it happen here by accident would make two tests report the same
    thing and neither report what it claims.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        gen = cleat.get(run_id)[1].get("generation", 0)
        if gen >= 1:
            return gen
        time.sleep(0.1)
    raise AssertionError(
        f"run {run_id} was never claimed within {timeout}s, so it has no "
        f"generation to act on"
    )


def test_force_complete_moves_a_running_workflow_to_done(cleat, retry_workflow):
    """An operator can terminate a run and supply its result.

    The run is deliberately long: forcing a workflow that has already finished
    tests nothing, and would pass against an endpoint that did nothing at all.
    """
    key = f"fc-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 5,
        "intervalMs": 3000, "failTimes": 999,
    })
    assert status == 201, f"start rejected: {status} {started}"

    code, body = cleat.admin(started["id"], "force-complete", {
        "generation": _claimed_generation(cleat, started["id"]),
        "result": json.dumps({"forced": True}),
    })
    assert code == 200, (
        f"force-complete answered {code}: {body!r}. A 200 carrying HTML rather "
        f"than JSON is cleat#830's shape; a 500 is cleat#832's."
    )

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the run was force-completed but is {final['status']!r}: {final!r}"
    )


def test_force_complete_without_the_confirmation_header_is_refused(cleat, retry_workflow):
    """The confirmation header is required, and its absence is a 400.

    A destructive operator action should not be reachable by a single
    mistyped URL. 400 specifically, not 500: cleat#832 was exactly this
    distinction, where a refusal was reported as a server fault.
    """
    key = f"fc-noconfirm-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 5,
        "intervalMs": 3000, "failTimes": 999,
    })
    assert status == 201, f"start rejected: {status} {started}"

    code, body = cleat.admin(started["id"], "force-complete",
                             {"generation": 1, "result": "{}"},
                             confirm="wrong-value")
    assert code == 400, (
        f"a missing confirmation answered {code}, not 400: {body!r}. "
        f"500 here is cleat#832 -- a refusal reported as a server fault."
    )

    cleat.cancel(started["id"])


def test_force_completing_an_unknown_run_is_a_404(cleat):
    """An id that does not exist is 404, not 500 and not 200.

    The 200 case is not hypothetical: under cleat#830 these paths fell through
    to the SPA handler, which answers 200 with HTML for any unmatched path. A
    test asserting only 'not 2xx' would have missed it, because it WAS 2xx.
    """
    code, body = cleat.admin(str(uuid.uuid4()), "force-complete",
                             {"generation": 1, "result": "{}"})
    assert code == 404, (
        f"an unknown run answered {code}: {body!r}. 200 means the request "
        f"reached the SPA fallback rather than the API (cleat#830); 500 means "
        f"the status came from the error message (cleat#832)."
    )


def test_a_stale_generation_is_refused_as_a_conflict(cleat, retry_workflow):
    """Forcing with the wrong generation is a 409, not a silent overwrite.

    Generation is the optimistic-concurrency token: an operator acting on a
    view of the run that has since moved on must be told, not obeyed. A
    generation far in the future cannot match any real one.
    """
    key = f"fc-gen-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 5,
        "intervalMs": 3000, "failTimes": 999,
    })
    assert status == 201, f"start rejected: {status} {started}"

    code, body = cleat.admin(started["id"], "force-complete",
                             {"generation": 999_999, "result": "{}"})
    assert code == 409, (
        f"a stale generation answered {code}, not 409: {body!r}. This is the "
        f"case cleat#832 reported as 500."
    )

    cleat.cancel(started["id"])


def test_force_fail_moves_a_running_workflow_to_failed(cleat, retry_workflow):
    """The failure counterpart, asserted separately from force-complete.

    The two share a handler shape and an error-classification path, so a defect
    in one is not evidence about the other -- and cleat#830 registered them as
    separate routes, either of which could have been the one left unserved.
    """
    key = f"ff-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": key, "attempts": 5,
        "intervalMs": 3000, "failTimes": 999,
    })
    assert status == 201, f"start rejected: {status} {started}"

    code, body = cleat.admin(started["id"], "force-fail", {
        "generation": _claimed_generation(cleat, started["id"]),
        "error": "forced by an operator in a port test",
    })
    assert code == 200, f"force-fail answered {code}: {body!r}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "failed", (
        f"the run was force-failed but is {final['status']!r}: {final!r}"
    )
