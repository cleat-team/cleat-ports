"""Identity under concurrency: a run reports its own id and nobody else's.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream file: `tests/test_concurrency.py`. Nine of its eleven cases are
unportable in principle -- they drive `asyncio.gather` inside a single
workflow, which cleat's determinism analyzer refuses at build time rather than
at run time (ISSUES.md 22, E001/E002/E012/E013). The two that remain are
synchronous and use threads to drive SEPARATE workflows, which is a thing cleat
does. This file is the first of those two.

WHY THIS IS WORTH A FILE RATHER THAN A LINE. `test_concurrent_workflows` reads
as a smoke test -- start ten workflows, they all finish -- and the assertion
that matters is not that they finish. It is that each one returns ITS OWN id.
That is the only case in the upstream file that would catch a host handing a
running workflow somebody else's identity, and cleat is the engine where that
is most expressible: one worker runs many workflows at once, each is a WASM
instance the host drives, and `RunID()` is answered out of host state rather
than out of anything the guest holds. A pooled instance, a reused context, or
an index into a slice of in-flight runs all produce the same symptom -- ten
workflows that complete perfectly and report the wrong identity.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_concurrent_runs_each_report_their_own_id(cleat, own_identity_workflow):
    """Ten overlapping runs, each returning the id it was started under.

    The hold is what makes this about concurrency. Without it each run can
    finish before the next is claimed, and ten sequential executions cannot
    demonstrate anything about identity under overlap -- the test would pass
    against a host that got this catastrophically wrong.

    The pairing is checked per run rather than as a set. Asserting that the ten
    returned ids EQUAL the ten started ids is a weaker claim that a full
    permutation satisfies: a host that gave every run its neighbour's identity
    would return exactly the right set of ids and pass. What has to hold is
    that each individual run reports the id it was started under.
    """
    hold_ms = 1500
    n = 10

    def start_one():
        status, started = cleat.start(own_identity_workflow, {"holdMs": hold_ms})
        assert status == 201, f"start rejected: {status} {started}"
        return started["id"]

    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=n) as pool:
        run_ids = [f.result() for f in [pool.submit(start_one) for _ in range(n)]]

    assert len(set(run_ids)) == n, (
        f"the engine issued {len(set(run_ids))} distinct ids for {n} starts, so "
        f"the identity assertion below could be satisfied by collision rather "
        f"than by correctness: {run_ids}"
    )

    reported = {}
    for run_id in run_ids:
        final = cleat.await_terminal(run_id, timeout=120.0)
        assert final["status"] == "done", (
            f"run {run_id} ended {final['status']!r}, not done: {final!r}. Ten "
            f"concurrent runs of a workflow that only sleeps should all complete."
        )
        reported[run_id] = _body(final)["runID"]
    elapsed = time.monotonic() - began

    # Did they actually overlap? Without this the test degrades silently: a
    # worker that ran the ten one after another would satisfy every assertion
    # below while demonstrating nothing about identity under concurrency, and
    # nothing in the output would say so. Serial execution costs n * hold_ms;
    # half of that is a generous line that still cannot be reached by ten
    # sequential 1.5s runs.
    serial_s = n * hold_ms / 1000.0
    assert elapsed < serial_s / 2, (
        f"the {n} runs took {elapsed:.1f}s, and running them one after another "
        f"costs {serial_s:.1f}s -- so they did not meaningfully overlap and this "
        f"is a test of ten sequential runs wearing a concurrency test's name. "
        f"Either the worker is serialising them or hold_ms is too short to keep "
        f"the earlier ones open while the later ones start."
    )

    mismatched = {k: v for k, v in reported.items() if k != v}
    assert not mismatched, (
        f"{len(mismatched)} of {n} concurrent runs reported an id that was not "
        f"their own: {mismatched}. Each key is the id the run was started "
        f"under and each value is what RunID() answered inside it, so a run "
        f"reporting another run's id means the host resolved identity against "
        f"the wrong in-flight entry. Every run still completed, which is why "
        f"this cannot be caught by a test that only checks they finish."
    )
