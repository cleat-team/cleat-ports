"""Parallel workflow execution, ported from dbos-transact-py's tests/test_async.py.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream reference:
  test_max_parallel_workflows  tests/test_async.py

This is the one portable case in that file. The work-list survey of
test_async.py found 33 cases: 11 already covered, 11 not engine assertions at
all, 9 needing something cleat does not have, 1 answered differently on
purpose -- and this one, which is portable and which **nothing in this port
already asserts**.

The closest existing test is test_concurrency.py::test_distinct_keys_do_not_
block_each_other, and it does not assert parallelism: it asserts that two
starts under different keys are both admitted (201) and both complete, which a
worker executing them one after another satisfies. It exists to stop its
neighbouring rejection test passing vacuously and it does that job. So this is
not an async mirror of a sync case -- it is an assertion the sync suite does
not make either.

WHY THERE IS NO CLOCK HERE.

Upstream asserts 50 workflows that each sleep 5s complete in under 30s, where
serial would take 250s. Porting that shape directly fails twice over:

  * `DurableSleepMs` SUSPENDS the run rather than occupying a worker slot, so
    fifty sleeping runs complete in about one sleep-duration whether the engine
    runs them one at a time or all at once. The transliteration is green on a
    strictly serial engine -- it measures nothing.
  * A threshold between two timings is the shape that went wrong in
    cleat-ports#115, where 3000ms was compared against 4500ms and a cold run's
    ~1s overhead landed between the hypotheses, reading as the defect upstream
    had shipped.

There is also a ceiling nobody would guess from the upstream numbers: the
separation available is bounded by the worker's -concurrency (10 by default,
cmd/cleat-worker/config.go:66, not overridden by scripts/worker.sh), so with N
workflows the best ratio is N/10 -- 50 workflows buy 5x, not the order of
magnitude the upstream figures suggest.

So the unit of work is a durable call the fixture service HOLDS OPEN, and the
service reports the largest number it had in flight at once. The assertion is a
direct measurement with no threshold to tune, and a serial engine produces
exactly 1.

The instrument was checked before it was trusted: 8 concurrent callers report a
peak of 8, the same 8 made one after another report 1, and an unused key
reports 0.
"""

import concurrent.futures
import uuid

import pytest

# Enough runs to fill the worker's default concurrency of 10 several times over,
# so the peak is not a function of how fast the test loop can issue starts.
RUNS = 24

# Long enough that overlap is unmistakable and the start loop cannot finish
# before the first call returns; short enough that RUNS/10 batches stay quick.
HOLD_MS = 1500


def _key() -> str:
    return f"port-parallel-{uuid.uuid4()}"


def test_workflows_run_in_parallel(cleat, parallel_unit_workflow, fixture_peak):
    """More than one workflow is mid-execution at the same moment.

    The assertion this port did not previously make anywhere.
    """
    key = _key()

    # Start concurrently: issuing 24 HTTP starts one at a time would take long
    # enough that the earliest runs could finish before the last begins, and a
    # low peak would then be an artefact of the test loop rather than of the
    # engine. This is about the client, not about what is being measured.
    with concurrent.futures.ThreadPoolExecutor(max_workers=RUNS) as pool:
        results = list(pool.map(
            lambda _: cleat.start(
                parallel_unit_workflow, {"key": key, "delayMs": HOLD_MS}),
            range(RUNS)))

    run_ids = []
    for status, body in results:
        assert status == 201, f"start should be accepted, got {status}: {body}"
        run_ids.append(body["id"])
    assert len(set(run_ids)) == RUNS, "each start should be a distinct run"

    # Every run must finish. This is the partner assertion, and it is not
    # decoration: a peak above 1 is also satisfied by an engine that overlapped
    # two runs and dropped the other 22, which would be a far worse defect than
    # the one under test.
    for run_id in run_ids:
        final = cleat.await_terminal(run_id, timeout=120.0)
        assert final["status"] == "done", (
            f"run {run_id} ended {final.get('status')!r} "
            f"error={final.get('error')!r}")

    peak = fixture_peak(key)
    assert peak > 1, (
        f"the fixture never held more than {peak} call open at once across "
        f"{RUNS} workflows, so nothing shows they overlapped -- a worker "
        f"executing them one after another produces exactly this. Worker "
        f"concurrency defaults to 10, so a healthy engine reports several.")


def test_parallel_execution_reaches_the_configured_concurrency(
        cleat, parallel_unit_workflow, fixture_peak):
    """Parallelism scales, rather than stopping at two.

    Separate from the test above because the two fail for different reasons and
    a reader should be able to tell them apart. `peak > 1` failing means the
    engine serialises. This one failing means it overlaps, but far below what
    the worker is configured for -- a claim-batch or dispatch-loop limit, not an
    execution one.

    The bound is deliberately loose. The exact peak depends on how the claim
    loop batches and how quickly starts are issued, and asserting a specific
    number would make this a timing test by another route. Three is chosen to be
    unmistakably more than the pairwise overlap the test above already covers,
    while staying far below the configured 10.
    """
    key = _key()

    with concurrent.futures.ThreadPoolExecutor(max_workers=RUNS) as pool:
        results = list(pool.map(
            lambda _: cleat.start(
                parallel_unit_workflow, {"key": key, "delayMs": HOLD_MS}),
            range(RUNS)))

    run_ids = [body["id"] for status, body in results if status == 201]
    assert len(run_ids) == RUNS, f"all {RUNS} starts should be accepted"

    for run_id in run_ids:
        final = cleat.await_terminal(run_id, timeout=120.0)
        assert final["status"] == "done", (
            f"run {run_id} ended {final.get('status')!r}")

    peak = fixture_peak(key)
    # The message must not assume WHICH side of the bound failed. An earlier
    # version read "More than one ran at a time, so the engine is not serial",
    # which is true only when peak is 2 -- and the falsification for this file
    # runs the worker with -concurrency 1, where peak is 1 and that sentence
    # states the opposite of what happened. A failure message that misdescribes
    # its own failure sends the next reader after the wrong mechanism.
    assert peak >= 3, (
        f"peak in-flight was {peak} across {RUNS} workflows against a worker "
        f"configured for 10 concurrent executions. "
        + ("A peak of 1 means nothing overlapped at all -- the engine is "
           "serial, and test_workflows_run_in_parallel above should have "
           "failed too; read that one first."
           if peak <= 1 else
           "More than one ran at a time, so the engine is not serial, but it "
           "is not reaching what it is configured for -- look at the claim "
           "batch and the dispatch loop rather than at execution."))


def test_serial_starts_show_no_overlap(cleat, parallel_unit_workflow, fixture_peak):
    """The negative control, kept as a test rather than run once by hand.

    The two assertions above rest entirely on the fixture's peak counter being
    able to report a LOW number. Nothing above can tell "the engine ran these
    in parallel" from "the counter is broken and always reports many" -- both
    produce a pass, which is the shape CLAUDE.md warns about: a check that was
    going to say yes whatever the truth was.

    So this drives the same workflow, the same fixture and the same counter
    through the same worker, but issues each start only after the previous run
    has finished. Genuinely serial work must report a peak of exactly 1. If
    this ever reports more, the instrument is counting something other than
    overlap and the tests above mean nothing.

    Deliberately few runs and a short hold: this asserts a property of the
    measurement, not of the engine, and three is enough to distinguish 1 from
    "more than 1".
    """
    key = _key()
    serial_runs = 3

    for _ in range(serial_runs):
        status, body = cleat.start(
            parallel_unit_workflow, {"key": key, "delayMs": 300})
        assert status == 201, f"start should be accepted, got {status}: {body}"
        final = cleat.await_terminal(body["id"], timeout=60.0)
        assert final["status"] == "done", (
            f"run ended {final.get('status')!r} error={final.get('error')!r}")

    peak = fixture_peak(key)
    assert peak == 1, (
        f"three runs issued strictly one after another reported a peak of "
        f"{peak}. Nothing overlapped, so the counter is measuring something "
        f"other than concurrent occupancy -- and the parallelism assertions "
        f"in this file are worthless until that is understood.")
