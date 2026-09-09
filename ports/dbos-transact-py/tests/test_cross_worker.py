"""Assertions that need two live workers against one database.

Everything here was listed in the README's "what this suite structurally
cannot catch" until the `second_worker` fixture existed. `cleat-worker` serves
the HTTP API and runs workflows in one process, and the harness started
exactly one -- so a property that distinguishes "serialised inside a process"
from "serialised in the database" could be described here and not asserted.

That distinction is the whole subject of this file. A test that contends for a
key through ONE API server exercises whatever that process does about it;
cleat's answer is a row in `concurrency_keys` with `key_hash` as PRIMARY KEY
and `ON CONFLICT DO NOTHING`, which is a claim about the database and not
about the process. Only a second process can tell those apart.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.
"""

import uuid

import pytest

from conftest import Cleat


def _key() -> str:
    return f"xworker-{uuid.uuid4().hex[:12]}"


def test_a_held_key_is_refused_from_a_second_worker(
    cleat, second_worker, api_key, holds_key_workflow
):
    """A key held via one worker is refused through the other.

    THE POINT IS THE SECOND PROCESS. test_concurrency.py already asserts that a
    second start under a held key is refused -- through the same worker, where
    a process-local map would satisfy it just as well as a database row. This
    is the same assertion with the two starts on opposite sides of a process
    boundary, so only the database can be doing the work.

    Both workers share the database, the API key and the fixture service, which
    is the configuration under test. If this passes while the single-worker
    version also passes, the exclusion is where cleat says it is.
    """
    other = Cleat(second_worker, api_key)
    assert other.base != cleat.base, (
        f"both clients point at {cleat.base}: this test would then assert "
        f"single-worker exclusion under a name that claims otherwise, and pass "
        f"for a reason it is written to rule out"
    )
    key = _key()

    status, first = cleat.start(holds_key_workflow, {"ms": 3000}, concurrency_key=key)
    assert status == 201, f"first start rejected: {status} {first}"

    status, body = other.start(holds_key_workflow, {"ms": 100}, concurrency_key=key)
    assert status == 409, (
        f"a key held through worker 1 was not refused through worker 2: got "
        f"{status} {body!r}. Two workers share one `concurrency_keys` table, so "
        f"a 201 here means the exclusion is process-local -- which would make "
        f"every single-worker concurrency assertion in this suite true of the "
        f"process and not of cleat."
    )


def test_distinct_keys_do_not_block_across_workers(
    cleat, second_worker, api_key, holds_key_workflow
):
    """The control, and it is not optional.

    Without it the test above passes against a worker that refuses every start
    it did not originate -- a broken second worker looks identical to correct
    mutual exclusion. This asserts the refusal is about the KEY.
    """
    other = Cleat(second_worker, api_key)

    status_a, a = cleat.start(holds_key_workflow, {"ms": 1500}, concurrency_key=_key())
    assert status_a == 201, f"first start rejected: {status_a} {a}"

    status_b, b = other.start(holds_key_workflow, {"ms": 100}, concurrency_key=_key())
    assert status_b == 201, (
        f"a start under a DIFFERENT key was refused through the second worker: "
        f"{status_b} {b!r}. The second worker is rejecting starts for some "
        f"reason other than key contention, so the exclusion test above proves "
        f"nothing."
    )
