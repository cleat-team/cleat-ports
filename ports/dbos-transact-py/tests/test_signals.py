"""Signal-await timeouts.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

DBOS's `recv` takes a timeout and returns None when nothing arrives. Cleat's
`DurableAwaitSignals` is the same shape, returning a timedOut flag.

This test earned its place by being the control that made cleat#814
diagnosable. The promise await and the signal await are written the same way --
record the await, suspend with `Until = now + timeout` -- so the question was
whether the promise defect was shared or particular. Running this said: the
signal await comes back `timedout` at generation 2, while the promise await was
at generation 31 and climbing. That contrast turned "promises hang" into "the
promise path is missing a timeout report the signal path has", which is a
different and much smaller problem.

Keeping it means the next person asking that question gets the answer for free
instead of writing the probe again.
"""

import json

import pytest

# Short: the assertion is that the timeout fires at all, and a long one only
# makes the suite slower without making the claim stronger.
TIMEOUT_MS = 5000


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_signal_await_times_out_when_nothing_arrives(cleat, signal_timeout_workflow):
    status, started = cleat.start(signal_timeout_workflow, {"timeoutMs": TIMEOUT_MS})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=90.0)
    assert final["status"] == "done", (
        f"a workflow waiting for a signal nobody sends did not complete: {final!r}. "
        "The timeout is the only thing that can end this wait."
    )

    body = _body(final)
    assert body["outcome"] == "timedout", (
        f"outcome was {body!r}. A signal await that neither receives nor times "
        "out leaves the workflow waiting forever, which is what cleat#814 was "
        "on the promise side."
    )
