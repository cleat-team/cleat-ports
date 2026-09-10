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

# What each dialect does with an integer past 2**53. MEASURED, not assumed --
# and it differs, which is cleat#1022.
#
# PostgreSQL's jsonb keeps numbers as `numeric`, so the value survives exactly.
# MySQL's JSON stores an integer exactly only to BIGINT and past that converts
# to DOUBLE, so it comes back as 1.2345678901234566e29 -- valid JSON, right
# shape, plausible, and a different number.
#
# SQL Server is deliberately absent rather than guessed: `result` there is a
# CHECK (ISJSON(...)) column, a third implementation, and nobody has measured
# it. The test skips with that reason and self-retires the moment a row is
# added, which a decorator skip would not.
BIG_INT_RETURNED = '{"x":123456789012345678901234567890}'
BIG_INT_STORED = {
    "postgres": {"x": 123456789012345678901234567890},
    "mysql": {"x": 1.2345678901234566e29},
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


def test_a_large_integer_result_keeps_whatever_precision_the_dialect_offers(
    cleat, bad_result_workflow
):
    """PINS cleat#1022: the same result is a different number on MySQL.

    This is the assertion that found it, and only because it compares against
    the exact value rather than checking the result "is a number" or "is an
    object" -- both of which pass on both dialects. The degraded value is valid
    JSON, the right shape, and plausible.
    """
    dialect = os.environ.get("CLEAT_PORTS_DIALECT", "postgres")
    if dialect not in BIG_INT_STORED:
        pytest.skip(
            f"what {dialect} does with an integer past 2**53 has not been measured; "
            f"add a row to BIG_INT_STORED once it has. See cleat#1022 -- postgres "
            f"keeps it exactly and mysql narrows it to a double, so a third answer "
            f"is entirely possible and guessing one would assert nothing."
        )

    final = _run(cleat, bad_result_workflow, "big-int")
    assert final["status"] == "done", f"big-int: {final}"
    assert _result(final) == BIG_INT_STORED[dialect], (
        f"big-int on {dialect}: expected {BIG_INT_STORED[dialect]!r}, got "
        f"{final['result']!r}.\n\n"
        "If this now matches what the workflow returned on a dialect that used to "
        "narrow it, cleat#1022 has been fixed and this row should be updated. If it "
        "narrows on a dialect that used to keep it, that is a regression."
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
