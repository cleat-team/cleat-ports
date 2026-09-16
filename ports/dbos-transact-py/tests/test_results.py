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
import os

import pytest

# `valid` is the control that makes the rest evidence: it proves the pipeline
# stores what it is given, so "the result came back {}" cannot be explained by
# an engine that discards everything.
VALID = '{"ok":true}'

# An integer past 2**53 survives the round trip EXACTLY, on every dialect.
#
# This used to be a per-dialect table, because it used to differ: PostgreSQL's
# jsonb keeps numbers as `numeric` and SQL Server's column is NVARCHAR(MAX) with
# an ISJSON check, so both survived; MySQL's native JSON type keeps an integer
# only to BIGINT and silently converts anything larger to DOUBLE. That was
# cleat#1022 -- the stored value stayed valid JSON, the right shape and entirely
# plausible, and was a different number.
#
# cleat#1626 closed it by porting SQL Server's representation to MySQL column
# for column: LONGTEXT + CHECK (JSON_VALID(col)). Its commit message states the
# intent this assertion now pins -- "All three dialects now preserve, rather
# than two agreeing and MySQL being documented as lesser."
#
# So the divergence this test was built to describe no longer exists, and the
# table went with it. A NEW dialect is held to the invariant rather than being
# skipped pending measurement: preserving the caller's JSON is the contract, not
# a property each backend gets to have its own answer to.
BIG_INT_RETURNED = '{"x":123456789012345678901234567890}'
BIG_INT_STORED = {"x": 123456789012345678901234567890}


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


def test_a_storable_result_survives_unchanged(cleat, bad_result_workflow):
    """CONTROL for the tests below, and load-bearing.

    Without it, "the result came back {}" is equally consistent with an engine
    that discards every result.
    """
    final = _run(cleat, bad_result_workflow, "valid")
    assert final["status"] == "done", f"valid: {final}"
    assert _result(final) == json.loads(VALID), (
        f"a storable result did not round-trip unchanged. got {final['result']!r}"
    )


def test_a_large_integer_result_survives_unchanged_on_every_dialect(
    cleat, bad_result_workflow
):
    """PINS the contract cleat#1626 established: the caller's JSON survives, intact.

    This is the assertion that found cleat#1022, and only because it compares
    against the exact value rather than checking the result "is a number" or "is
    an object" -- both of which passed while MySQL was silently rewriting it.
    The degraded value was valid JSON, the right shape, and plausible. Keep the
    exact comparison: every weaker check this test could make was already passing
    on the broken dialect.

    Now that all three preserve, the failure directions are worth naming because
    they are not symmetric:

      * narrows on ANY dialect -> a regression in that dialect's column type or
        its write path. cleat#1626 made MySQL LONGTEXT + CHECK (JSON_VALID(col));
        a migration that puts the native JSON type back reintroduces cleat#1022
        without erroring, exactly as it did the first time.
      * fails on a NEW dialect -> not a gap in this test. The invariant is the
        contract; a backend that cannot hold the caller's JSON has to say so
        rather than store a different number.
    """
    dialect = os.environ.get("CLEAT_PORTS_DIALECT", "postgres")

    final = _run(cleat, bad_result_workflow, "big-int")
    assert final["status"] == "done", f"big-int: {final}"
    assert _result(final) == BIG_INT_STORED, (
        f"big-int on {dialect}: expected {BIG_INT_STORED!r}, got "
        f"{final['result']!r}.\n\n"
        f"The workflow returned {BIG_INT_RETURNED}. Every dialect is required to "
        "give it back unchanged (cleat#1022, closed by cleat#1626). A value that "
        "is still valid JSON and still the right shape but a DIFFERENT NUMBER is "
        "the signature of a JSON column that reparses numerically -- check this "
        "dialect's column type for the result/input/payload columns before "
        "looking anywhere else."
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


# The characters the fixture returns, decoded. Written as escapes in the Go
# source and compared as real code points here, so the assertion fails if the
# engine hands back the ESCAPES rather than the characters -- which is a real
# outcome and a passing one for a naive string comparison against the raw JSON.
UNICODE_EXPECTED = {
    "cjk": "世界",
    "accent": "café",
    "astral": "\U0001F680",
    "quoted": 'say "hi"',
}


def test_a_non_ascii_result_survives_all_three_dialects(cleat, bad_result_workflow):
    """A result the store ACCEPTS must also come back unmangled.

    Every other case in this file asks whether a value is rejected. This asks
    the opposite question about a value that is accepted everywhere, and the
    three dialects answer it with different machinery: `JSONB` on Postgres,
    `JSON` on MySQL, and `NVARCHAR(MAX)` behind a `CHECK (ISJSON(...))` on SQL
    Server.

    **Why it is worth a case when all three currently hold it.** The failure it
    guards is silent in exactly the way this file's docstring describes: a
    narrowing to `VARCHAR`, or a connection charset that is not `utf8mb4`,
    substitutes `?` for characters it cannot represent and leaves the run
    `done` with an empty `error_msg`. A caller sees a successful workflow and a
    corrupted result. Checked before writing this: SQL Server's column is
    `nvarchar(-1)` — that is `NVARCHAR(MAX)` — so it holds today, and this
    pins it.

    **Found by verifying a coverage claim, not by suspecting a bug.**
    `durabletask-go`'s `Test_SingleActivity` asserts its output is
    `"Hello, 世界!"`, and the survey classified that case as already covered
    here. The completion half was; the unicode half was not. Nothing in this
    port put a non-ASCII byte in an input or an asserted result — 46 lines
    contained non-ASCII and every one was an em-dash in prose.

    **This is not the limit `test_scheduling.py` records.** That one is real and
    is about the FIXTURE KEY channel: keys travel in a URL path and
    `http.client` encodes the request line as ASCII, so a non-ASCII key raises
    `UnicodeEncodeError` in the test process. A workflow result travels in a
    JSON body and is unaffected — different channel, and that note says so.

    The astral character matters on its own: `U+1F680` is outside the BMP, so
    SQL Server stores it as a UTF-16 surrogate pair. A layer that counts
    characters rather than code units can split it, which produces a lone
    surrogate rather than a substitution and fails differently.
    """
    final = _run(cleat, bad_result_workflow, "unicode")
    assert final["status"] == "done", f"the run did not complete: {final}"

    got = _result(final)
    assert got == UNICODE_EXPECTED, (
        f"a non-ASCII result did not round-trip. got {got!r}, want "
        f"{UNICODE_EXPECTED!r}. Question marks mean the column or the "
        "connection charset cannot represent the character; escaped text like "
        r"'世' means something returned the JSON source rather than "
        "decoding it."
    )
