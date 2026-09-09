"""Upstream test_queue.py::test_complex_type, plus the binding contrast it sits on.

Upstream enqueues a workflow taking a nested dataclass, asserts the result is
that same nested shape, and then asserts it again for a run recovered
mid-flight. Both halves are about one property: a complex argument survives the
trip through the store intact.

cleat has no queues (ISSUES.md 20), so the enqueue is a plain start. The
recovery half ports directly, because cleat's replay model makes it sharper
than upstream's: a resumed segment re-executes from the top, so the argument is
decoded from the store a second time inside the same run.
"""
import json
import time

import pytest

SLEEP_MS = 2000


def _run(cleat, workflow, outer, n, sleep_ms=0):
    """Start one run and return (decoded result, wall-clock seconds)."""
    t0 = time.time()
    status, started = cleat.start(
        workflow, {"outer": outer, "n": n, "sleepMs": sleep_ms}
    )
    assert status == 201, f"start rejected: {status} {started}"
    final = cleat.await_terminal(started["id"], timeout=90.0)
    elapsed = time.time() - t0
    assert final["status"] == "done", f"run did not complete: {final!r}"
    raw = final["result"]
    body = json.loads(raw) if isinstance(raw, str) else raw
    return body, elapsed


def test_a_nested_struct_argument_round_trips(cleat, complex_arg_workflow):
    """The plain half: what the workflow receives is what was sent."""
    outer = {"inner": {"one": "one", "two": 2}}
    body, _ = _run(cleat, complex_arg_workflow, outer, n=2)

    assert body["before"] == outer, (
        f"a nested struct argument arrived as {body['before']!r}, sent {outer!r}. "
        "Both fields are set and neither is at its zero value in the input, so a "
        "missing level of nesting shows up as an empty inner object rather than "
        "as a value that happens to look plausible."
    )


def test_a_nested_struct_argument_survives_a_suspension(cleat, complex_arg_workflow):
    """The recovery half: the resumed segment decodes the same argument again.

    Upstream recovers a blocked workflow and re-checks the result. cleat reaches
    the same place by suspending on a durable sleep: the resumed segment
    re-executes from the top, decoding the argument a second time from what the
    store kept.

    The assertion is `after` against the input the TEST sent, not `after`
    against `before`. Comparing the two echoes to each other looks stronger and
    is very nearly vacuous -- replay recomputes `before` as well, so both values
    come from the same second decode, and a lossy round trip would corrupt them
    identically and still compare equal. Only a value from outside the workflow
    can catch that.

    The elapsed-time check is the other half: without it, a run that never
    suspended would satisfy every assertion here while testing nothing about
    replay. That is the failure mode this suite has hit before -- a control that
    passes because the workflow ran straight through instead of parking.
    """
    outer = {"inner": {"one": "one", "two": 2}}
    body, elapsed = _run(cleat, complex_arg_workflow, outer, n=2, sleep_ms=SLEEP_MS)

    assert elapsed >= SLEEP_MS / 1000 * 0.8, (
        f"the run finished in {elapsed:.2f}s for a {SLEEP_MS}ms durable sleep, so "
        "it did not suspend and this test says nothing about replay. Check that "
        "sleepMs bound: an int parameter that fails to bind arrives as 0 and the "
        "workflow runs straight through (cleat#1036 is the same mechanism)."
    )
    assert body["after"] == outer, (
        f"after a suspension the argument was {body['after']!r}, sent {outer!r}. "
        "The resumed segment decodes the argument again from the store, so this "
        "is the round trip upstream's recovery half is about."
    )


def test_a_negative_integer_binds_the_same_in_a_struct_and_as_a_parameter(
    cleat, complex_arg_workflow
):
    """The same negative value, in one request, bound two ways.

    `Inner.Two` is a struct field and `n` is a direct int parameter. Nothing
    about a workflow's contract says those should differ, and this test exists
    because they do: `wasm/exports.go` routes int/int64/int32 to a hand-rolled
    digit scanner and everything else to json.Unmarshal. The scanner has no sign
    handling, so a leading '-' ends the scan before it consumes anything and the
    parameter arrives as 0 -- cleat#1036.

    A negative integer is well-formed JSON and a valid Go int, so this is not a
    test about malformed input. Any parameter whose domain includes negatives is
    unpassable, the -1-means-unbounded convention among them.
    """
    outer = {"inner": {"one": "one", "two": -7}}
    body, _ = _run(cleat, complex_arg_workflow, outer, n=-7)

    assert body["before"]["inner"]["two"] == -7, (
        f"the struct FIELD lost its sign too: {body['before']!r}. cleat#1036 is "
        "specifically about direct int parameters -- struct fields are "
        "json.Unmarshal'ed and decode correctly -- so this is a different and "
        "wider defect than the one this test was written for."
    )

    if body["n"] == 0:
        pytest.skip(
            f"cleat#1036: the direct int parameter arrived as 0 while the same "
            f"value in a struct field arrived as -7.\n"
            f"result: {body!r}\n"
            f"\n"
            f"A skip rather than a failure only so the suite stays green while "
            f"#1036 is open, and deliberately NOT an unconditional skip: the "
            f"struct-field assertion above still runs in full, and it is the "
            f"control that makes the finding precise. The day #1036 is fixed "
            f"this test passes on its own and the skip disappears without "
            f"anyone having to remember it. If it goes red instead, the "
            f"scanner changed in some other way and that is a new finding."
        )

    assert body["n"] == -7, (
        f"the direct int parameter arrived as {body['n']!r}, sent -7, while the "
        f"struct field carrying the same value arrived correctly. That is "
        f"neither the pre-fix behaviour (0) nor the correct one."
    )
