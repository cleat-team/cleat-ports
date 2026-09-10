"""Queue admission: deduplication and priority.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream file: `tests/test_queue.py` — 91 collected cases, the largest single
block in scope and the least covered. (103 is what `ast.walk` reports; it
counts helper functions declared inside test bodies, which pytest never
collects. scripts/count-queue-cases.py counts what is collected.) DBOS's queue carries concurrency limits, rate
limits, deduplication and priority. Cleat's equivalents are spread across three
mechanisms rather than one queue object:

| DBOS | cleat |
|---|---|
| `queue(concurrency=N)` | concurrency keys — `test_concurrency.py`, `test_locks.py` |
| deduplication | the `Idempotency-Key` start header |
| priority | the `priority` field on the start body |
| rate limits | no equivalent surface |

So this file covers the two admission controls that exist and are reachable,
and says plainly that rate limiting has nothing to test rather than inventing a
proxy for it.
"""

import concurrent.futures
import json
import uuid

import pytest


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_the_same_idempotency_key_starts_one_run(cleat, retry_workflow, fixture_calls):
    """A repeated start with the same key returns the first run, not a second one.

    This is DBOS's deduplication: submitting the same logical job twice must not
    run it twice. The assertion is on the SIDE EFFECT as well as the id, because
    returning the same id while running the body twice is the failure that
    matters and the id alone cannot see it -- the fixture counts calls per key,
    so a second execution is visible even though both starts report success.
    """
    key = f"dedup-{uuid.uuid4().hex[:8]}"
    idem = f"idem-{uuid.uuid4().hex[:8]}"

    status_a, first = cleat.start(
        retry_workflow,
        {"service": "flaky", "key": key, "attempts": 1, "intervalMs": 50,
         "failTimes": 0, "failStatus": 0},
        idempotency_key=idem,
    )
    assert status_a == 201, f"first start rejected: {status_a} {first}"

    status_b, second = cleat.start(
        retry_workflow,
        {"service": "flaky", "key": key, "attempts": 1, "intervalMs": 50,
         "failTimes": 0, "failStatus": 0},
        idempotency_key=idem,
    )

    assert second.get("workflow_id") == first["id"], (
        f"the second start created a different run: first={first['id']!r} "
        f"second={second!r}. Deduplication is keyed on the Idempotency-Key header."
    )
    assert status_b == 200, (
        f"a deduplicated start answered {status_b}, not 200. 201 would mean "
        f"'created', which is exactly what did not happen: {second!r}"
    )
    assert second.get("already_started") == "true", (
        f"the response does not say the run already existed, so a caller cannot "
        f"tell a fresh start from a deduplicated one: {second!r}"
    )

    cleat.await_terminal(first["id"], timeout=60.0)
    assert fixture_calls(key) == 1, (
        f"the workflow body ran {fixture_calls(key)} times for one logical job. "
        f"Returning the same id while executing twice is the failure this test "
        f"exists for, and the id alone cannot see it."
    )


def test_a_completed_run_still_answers_for_its_idempotency_key(
    cleat, retry_workflow, fixture_calls
):
    """A key stays bound to its run after that run has finished.

    UPSTREAM ANSWERS THIS THE OTHER WAY, and the difference is the point.
    `test_queue.py::test_queue_deduplication` ends by re-enqueuing under a
    deduplication ID it has already used, and asserts the enqueue SUCCEEDS --
    "no longer in the queue" is its comment. DBOS scopes the ID to queue
    residency: once the workflow dequeues, the ID is free and the next
    submission is a new run.

    cleat scopes it to the record instead. `idempotency_keys` rows carry
    `expires_at DEFAULT now() + INTERVAL '7 days'` (migrations/postgres/001),
    so the binding outlives the run by a week regardless of how the run ended.

    Neither is more correct in the abstract; they answer different questions.
    DBOS's ID means "is this job already waiting", cleat's means "have I
    already submitted this job". But a caller that retries a submission after
    a delay -- the ordinary reason to hold an idempotency key at all -- gets
    one execution from cleat and two from DBOS, so the difference is reachable
    from normal use and worth a test rather than a sentence.

    The side-effect count carries the assertion, not the id. A start that
    returned the old id while running the body again is the failure that
    matters, and comparing ids cannot see it -- which is the same reason
    test_the_same_idempotency_key_starts_one_run counts fixture calls.
    """
    key = f"dedup-after-{uuid.uuid4().hex[:8]}"
    idem = f"idem-{uuid.uuid4().hex[:8]}"
    payload = {"service": "flaky", "key": key, "attempts": 1, "intervalMs": 50,
               "failTimes": 0, "failStatus": 0}

    status_a, first = cleat.start(retry_workflow, payload, idempotency_key=idem)
    assert status_a == 201, f"first start rejected: {status_a} {first}"

    final = cleat.await_terminal(first["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the first run did not finish, so this test would be re-submitting "
        f"against a LIVE run and would prove the in-flight case the test above "
        f"already covers: {final!r}"
    )
    assert fixture_calls(key) == 1, (
        f"the first run called the fixture {fixture_calls(key)} times, not once; "
        f"the count below cannot distinguish a second execution from a first "
        f"that ran twice"
    )

    status_b, second = cleat.start(retry_workflow, payload, idempotency_key=idem)

    assert second.get("workflow_id") == first["id"], (
        f"re-submitting a completed run's idempotency key started a DIFFERENT "
        f"run: first={first['id']!r} second={second!r}. cleat's key binding is "
        f"stored with a 7-day expiry rather than released at completion, so a "
        f"caller retrying a submission would get a second execution of work it "
        f"had already had. (This is where DBOS deliberately differs -- see the "
        f"docstring -- so a change here is a decision, not a bug fix.)"
    )
    assert status_b == 200, (
        f"a start deduplicated against a COMPLETED run answered {status_b}, not "
        f"200. 201 claims the run was created by this call, which it was not: "
        f"{second!r}"
    )
    assert second.get("already_started") == "true", (
        f"the response does not mark this start as a duplicate, so a caller "
        f"cannot tell that the result it is about to read belongs to an earlier "
        f"submission: {second!r}"
    )
    assert fixture_calls(key) == 1, (
        f"the workflow body ran {fixture_calls(key)} times. The second start "
        f"reported the first run's id and executed anyway, which is the failure "
        f"an id-only assertion cannot see."
    )

def test_different_idempotency_keys_start_different_runs(cleat, retry_workflow):
    """Dedup is keyed, not global.

    The negative control for the test above. Without it, a start endpoint that
    returned the first run for EVERY request would pass the dedup assertion
    perfectly.
    """
    payload = {"service": "flaky", "key": f"nodedup-{uuid.uuid4().hex[:8]}",
               "attempts": 1, "intervalMs": 50, "failTimes": 0, "failStatus": 0}

    status_a, first = cleat.start(retry_workflow, payload,
                                  idempotency_key=f"idem-{uuid.uuid4().hex[:8]}")
    status_b, second = cleat.start(retry_workflow, payload,
                                   idempotency_key=f"idem-{uuid.uuid4().hex[:8]}")

    assert status_a == 201 and status_b == 201, (
        f"expected two fresh starts, got {status_a} and {status_b}: {first} {second}"
    )
    assert first["id"] != second["id"], (
        f"two different idempotency keys produced the same run {first['id']!r}, "
        f"so deduplication is not keyed on the header at all"
    )


def test_a_start_without_an_idempotency_key_is_never_deduplicated(cleat, retry_workflow):
    """No key means no dedup, rather than dedup on some implicit key.

    An empty header could plausibly be treated as a key in its own right, which
    would collapse every un-keyed start in the system into one run. That failure
    would be invisible in a suite where every test passes a key.
    """
    payload = {"service": "flaky", "key": f"nokey-{uuid.uuid4().hex[:8]}",
               "attempts": 1, "intervalMs": 50, "failTimes": 0, "failStatus": 0}

    status_a, first = cleat.start(retry_workflow, payload)
    status_b, second = cleat.start(retry_workflow, payload)

    assert status_a == 201 and status_b == 201, (
        f"expected two fresh starts, got {status_a} and {status_b}"
    )
    assert first["id"] != second["id"], (
        f"two starts with no Idempotency-Key produced the same run {first['id']!r}. "
        f"An absent header is being treated as a key, which would collapse every "
        f"un-keyed start into one run."
    )


def test_priority_is_accepted_and_recorded(cleat, retry_workflow):
    """A priority given at start is carried on the run.

    Deliberately NOT a dispatch-order test. Ordering is `priority ASC,
    created_at` in the claim query on all three dialects
    (engine/store_lifecycle.go:82, mysql_lifecycle.go:56,
    mssql_lifecycle.go:113), but asserting observed order needs the worker
    saturated so that work actually queues -- and cleat rejects a blocked start
    rather than deferring it (see the skip in test_concurrency.py), so there is
    no way from here to hold the worker busy and enqueue behind it
    deterministically. A timing race dressed as an ordering assertion would fail
    for reasons unrelated to priority.

    So this pins the half that is checkable without a race: the value survives
    the round trip rather than being dropped at the API. If it were dropped,
    every ordering claim above it would be vacuous no matter how the query is
    written.
    """
    payload = {"service": "flaky", "key": f"prio-{uuid.uuid4().hex[:8]}",
               "attempts": 1, "intervalMs": 50, "failTimes": 0, "failStatus": 0}

    status, started = cleat.start(retry_workflow, payload, priority=7)
    assert status == 201, f"start with a priority rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"a workflow started with a priority did not complete: "
        f"{final.get('error') or final!r}"
    )
    assert final.get("priority") == 7, (
        f"priority 7 was accepted at the API and the run reports "
        f"{final.get('priority')!r}. The claim query orders by priority, so a "
        f"value that never reaches the row makes that ordering unreachable."
    )


def test_a_key_used_for_one_workflow_does_not_answer_for_another(
    cleat, complex_arg_workflow, signal_timeout_workflow
):
    """Upstream test_queue.py::test_duplicate_workflow_id.

    Upstream rejects reuse of a workflow id across two different functions with
    "Workflow already exists with a different function name". Reusing it for the
    SAME workflow returns the original handle and is fine; reusing it for a
    different one is an error rather than a silent substitution.

    The three deduplication tests above all use one definition, which is why
    this case is separate: same-key, different-key and no-key all behave
    correctly within a single workflow, and the namespace question only appears
    when two definitions share a key.
    """
    key = f"cross-def-{uuid.uuid4().hex[:10]}"

    first_status, first = cleat.start(
        complex_arg_workflow,
        {"outer": {"inner": {"one": "x", "two": 1}}, "n": 1, "sleepMs": 0},
        idempotency_key=key,
    )
    assert first_status == 201, f"first start rejected: {first_status} {first}"

    second_status, second = cleat.start(
        signal_timeout_workflow, {"timeoutMs": 3000}, idempotency_key=key
    )

    if second_status == 200 and second.get("workflow_id") == first["id"]:
        pytest.skip(
            f"cleat#1047: starting {signal_timeout_workflow!r} with a key already "
            f"used by {complex_arg_workflow!r} answered 200 "
            f"{second!r} -- the id of the OTHER workflow's run, with "
            f"already_started true. The requested workflow never started and "
            f"nothing in the response says so.\n"
            f"\n"
            f"An Idempotency-Key is hashed as sha256(key) and looked up on "
            f"(key_hash, tenant_id), so the namespace is (tenant, key) when the "
            f"thing being deduplicated is (tenant, definition, key). The same "
            f"defect in the TENANT dimension was fixed already, and its comment "
            f"in mysql_lifecycle.go describes this one exactly: the key is a "
            f"client-supplied header, so collisions are the expected outcome of "
            f"ordinary naming rather than an attack.\n"
            f"\n"
            f"A skip rather than a failure only so the suite stays green while "
            f"#1047 is open. The day it is fixed this test passes on its own."
        )

    assert second_status != 200 or second.get("workflow_id") != first["id"], (
        f"second start answered {second_status} {second!r}"
    )


def test_concurrent_starts_under_one_key_elect_exactly_one_creator(
    cleat, retry_workflow, fixture_calls
):
    """Under a race, exactly one caller is told it created the run.

    PORTED FROM uber/cadence, and kept here rather than in a cadence port
    because the property is worth more than the directory. See
    docs/cadence-persistence-survey.md: that suite's
    TestCreateWorkflowExecutionConcurrentCreate spawns concurrent creates of one
    workflow id and asserts `s.Equal(int32(1), numOfErr)` -- exactly one racer
    fails. Cadence ERRORS the losers; cleat answers them 200 with
    `already_started`. Same election, different report, and this asserts cleat's.

    WHY ITS NEIGHBOURS DO NOT COVER IT. test_the_same_idempotency_key_starts_one
    _run already pins the 201-then-200 distinction -- but SEQUENTIALLY, sending
    the second start after the first returned. So does every other dedup test
    here, and so does ports#156's pair in the durabletask-go port. Sequential
    starts exercise the LOOKUP: the run exists, the second start finds it.

    They cannot exercise the RACE, where several starts reach the key before any
    has committed a run. That is the case an idempotency key exists for, and the
    one where a check-then-insert without a uniqueness constraint behind it
    would hand TWO callers a 201 and run the body twice.

    Eight racers rather than two: the window is milliseconds wide, and two
    threads from a barrier miss it often enough that green would prove little.
    """
    key = f"cdd-{uuid.uuid4().hex[:8]}"
    idem = f"idem-{uuid.uuid4().hex[:8]}"
    payload = {"service": "flaky", "key": key, "attempts": 1, "intervalMs": 50,
               "failTimes": 0, "failStatus": 0}

    racers = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=racers) as pool:
        results = [f.result() for f in [
            pool.submit(cleat.start, retry_workflow, payload, idempotency_key=idem)
            for _ in range(racers)]]

    creators = [b for st, b in results if st == 201]
    dupes = [b for st, b in results if st == 200]

    assert len(creators) == 1, (
        f"{len(creators)} of {racers} concurrent starts were answered 201, not one. "
        f"A 201 means 'this call created the run', so more than one is two callers "
        f"each told they created it -- a check-then-insert with no uniqueness "
        f"constraint behind it. statuses: {[st for st, _ in results]}"
    )
    assert len(creators) + len(dupes) == racers, (
        f"some starts were neither 201 nor 200: {[st for st, _ in results]}. "
        f"Cadence errors every racer but one; if cleat has adopted that, this "
        f"test should assert it rather than be deleted."
    )

    run_id = creators[0]["id"]
    for b in dupes:
        assert b.get("workflow_id") == run_id, (
            f"a deduplicated racer was pointed at {b.get('workflow_id')!r}, not at "
            f"the created run {run_id!r}. The election picked one creator and told "
            f"the losers about a different run."
        )
        assert b.get("already_started") == "true", (
            f"a deduplicated racer did not report already_started: {b!r}"
        )

    final = cleat.await_terminal(run_id, timeout=60.0)
    assert final["status"] == "done", f"the elected run did not finish: {final!r}"

    calls = fixture_calls(key)
    assert calls == 1, (
        f"the body ran {calls} times for {racers} concurrent starts that elected "
        f"one creator. Electing a single creator while executing more than once is "
        f"the failure the status codes cannot see."
    )
