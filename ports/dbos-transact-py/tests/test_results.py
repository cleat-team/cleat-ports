"""What happens to a workflow result the store cannot hold.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS asserts that a workflow returning something its serializer cannot encode
FAILS -- the point being that a value which cannot be recorded must not be
reported as a recorded success. Upstream's case is pickle; the property is not
specific to an encoding, and JSON has its own unstorable values.

Cleat answers differently, and the difference is the subject here rather than a
defect this file claims. An entry point returns a string that the engine puts
in `workflow_instances.result` -- JSONB on Postgres, JSON on MySQL, a
CHECK (ISJSON(...)) column on SQL Server. A result that no dialect can hold is
replaced with `{}` by `coerceResultJSON`, and the workflow completes `done`.

WHAT IS AND IS NOT SILENT, because the distinction took a trace to establish
and the obvious write-up is wrong. The engine logs an ERROR naming the workflow
and the discarded value:

    workflow result is not valid JSON and was replaced with {} -- whatever it
    carried, including any error the workflow returned, is not stored anywhere

So an operator reading worker logs can see it. A CALLER cannot: status is
`done`, `error_code` and `error_msg` are empty, and `result` is `{}`. These
tests assert the caller's view, which is the half a port can reach.
"""

import json

import pytest

# The results, and what each one is for. Two of these are controls and the file
# is not evidence of anything without them: `valid` proves the pipeline stores
# what it is given, and `big-int` proves it does not mangle values merely for
# being awkward -- without that, "the result came back {}" is equally
# consistent with an engine that discards everything.
CASES = {
    "valid": '{"ok":true}',
    "big-int": '{"x":123456789012345678901234567890}',
    "bare-string": None,
    "nan": None,
    "inf": None,
}


def _run(cleat, workflow, kind):
    """Start one case and return its terminal record.

    The payload is nested under the PARAMETER name. A struct parameter binds by
    the Go parameter's name, not by the struct's fields: `{"req": {"kind": ...}}`
    reaches the workflow and `{"kind": ...}` does not -- the latter leaves `req`
    empty and every case fails identically inside the generated stub with
    `unmarshal req: unexpected end of JSON input`. Measured; the analyzer's own
    W003 suggestion reads as though the fields bind directly.
    """
    status, started = cleat.start(workflow, {"req": {"kind": kind}})
    assert status == 201, f"start rejected: {status} {started}"
    return cleat.await_terminal(started["id"], timeout=90.0)


def _result(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


@pytest.mark.parametrize("kind", ["valid", "big-int"])
def test_a_storable_result_survives_unchanged(cleat, bad_result_workflow, kind):
    """CONTROL for the two tests below, and load-bearing.

    `big-int` is past 2**53, so it also pins that the value is not passed
    through a float on the way to the column -- a reader that decoded it as a
    double would return 1.2345678901234568e+29 and still look like a success.
    """
    final = _run(cleat, bad_result_workflow, kind)
    assert final["status"] == "done", f"{kind}: {final}"
    assert _result(final) == json.loads(CASES[kind]), (
        f"{kind}: a storable result did not round-trip unchanged. "
        f"got {final['result']!r}"
    )


@pytest.mark.parametrize("kind", ["bare-string", "nan", "inf"])
def test_a_result_the_store_cannot_hold_is_replaced_and_the_run_reports_success(
    cleat, bad_result_workflow, kind
):
    """PINS CLEAT'S BEHAVIOUR, which differs from upstream's.

    Upstream fails the workflow. Cleat completes it and substitutes `{}`, so a
    caller who asked for a value receives an empty object and a `done` status
    with no error of any kind.

    This asserts what cleat does today rather than what upstream asserts,
    because the difference is a design question -- see ISSUES.md. If it is
    resolved in upstream's direction this test must be inverted, and its
    failure message says so rather than leaving the next reader to guess.
    """
    final = _run(cleat, bad_result_workflow, kind)

    if final["status"] != "done":
        pytest.fail(
            f"{kind}: the workflow did NOT complete -- status {final['status']}, "
            f"error {final.get('error')!r}.\n\n"
            "That is upstream's behaviour and this test is now wrong: cleat has "
            "started failing a workflow whose result it cannot store. Invert it "
            "and update the ISSUES.md entry, which records the difference."
        )

    assert _result(final) == {}, (
        f"{kind}: expected the substituted empty object, got {final['result']!r}"
    )
    assert not final.get("error"), (
        f"{kind}: a caller now sees an error ({final['error']!r}) where none was "
        "reported before. That is an improvement and this assertion is what "
        "notices it -- the point of this test is that the caller cannot tell."
    )
