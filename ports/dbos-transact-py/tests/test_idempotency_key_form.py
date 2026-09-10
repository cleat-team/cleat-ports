"""What counts as an idempotency key, and what is treated as none at all.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Maps to `test_client_enqueue_rejects_empty_workflow_id` in upstream's
`tests/test_client.py` (their #759, parametrized over three blank forms): an
empty or whitespace id must be *rejected* rather than stored verbatim, and
`_workflow_exists` then confirms nothing was written.

cleat generates the run id server-side, so the direct analogue does not exist.
The nearest caller-supplied identifier is the `Idempotency-Key` header, and the
property that ports is the one underneath upstream's assertion: **a blank
identifier must not become a real one.** If it did, two unrelated requests that
each sent a blank key -- which is what an unset template variable renders as --
would deduplicate against each other, and the second caller would be handed the
first caller's run.

WHAT THIS FOUND, AND IT IS THE OPPOSITE OF WHAT WAS EXPECTED. The survey that
produced this case (cleat-ports#111) read the code and predicted a defect: the
handler does `r.Header.Get("Idempotency-Key")` with no trim
(cmd/cleat-worker/server.go), and the store guard is a bare `!= ""` on all
three dialects -- store_lifecycle.go, mysql_lifecycle.go, mssql_lifecycle.go.
`"   " != ""`, so a whitespace key looked like a real one. That reading was
recorded as "read, not run" and deliberately not filed as a defect.

Run, it does not reproduce. A whitespace-only key is treated as absent.

**The reason is a layer nobody in cleat chose.** Go's `net/textproto` trims
leading and trailing whitespace from header values while parsing the request,
so `"   "` reaches the handler as `""` and never meets the `!= ""` guard at
all. That is not a cleat check -- it is the HTTP library, and the last test
here is what shows it: a padded key and a bare key **collide**, which can only
happen if the padding was removed before either was stored.

So this file pins a property cleat has, names the layer holding it up, and
would go red if the key ever moved somewhere that layer does not reach -- a
JSON body field, say, where `!= ""` is the whole guard and `"   "` passes it.
Watching which layer holds a test up is the point rather than a footnote:
`StartNewRun`'s only two callers that pass a non-empty key are this handler and
the scheduler. The scheduler's key is not free of caller input -- it is
`fmt.Sprintf("cron:%s:%s:%d", tenantID, sch.Name, scheduled.UTC().Unix())`, and
`sch.Name` is whatever an operator named the schedule. What makes it safe is the
TEMPLATE, not the absence of caller input: the literal `cron:` prefix and the
Unix timestamp mean the result is non-empty and non-blank whatever the name is.

That distinction is the thing to re-check if the template ever changes. An
earlier version of this comment said the key was "engine-generated", which is
the right conclusion by the wrong mechanism -- and a reader asking "can a caller
influence this key?" would have been told no, which is false.
"""

import time
import uuid

import pytest


def run_id(body):
    """The run id, whichever of the two shapes the response used.

    A fresh start answers `{"id": ...}` and a deduplicated one answers
    `{"already_started": "true", "workflow_id": ...}`. Reading only `id` makes
    every deduplicated response look like a *different* run, which inverts the
    result of every test in this file -- measured, while probing this case,
    against a control that was known to deduplicate.
    """
    return body.get("id") or body.get("workflow_id")


def start_twice(cleat, workflow, key_a, key_b):
    """Two starts with different payloads, returning (status, body) for each."""
    def payload(mark):
        return {"service": "flaky", "key": mark, "attempts": 1, "intervalMs": 50,
                "failTimes": 0, "failStatus": 0}
    first = cleat.start(workflow, payload(f"a-{uuid.uuid4().hex[:8]}"), idempotency_key=key_a)
    second = cleat.start(workflow, payload(f"b-{uuid.uuid4().hex[:8]}"), idempotency_key=key_b)
    return first, second


# The three blank forms upstream parametrizes over. A tab is included because
# it is the one a `\t`-joined template produces and the one a reader is least
# likely to assume is covered by "empty".
#
# A PLAIN LIST OF LITERALS, and not `pytest.param(..., id=...)`, which reads
# better and would be wrong here. `scripts/count-queue-cases.py` expands a
# parametrize to get the case count CI checks, and its `_parametrize_multiplier`
# returns 1 for any list it cannot `ast.literal_eval` -- deliberately, "rather
# than guessing". A `pytest.param(...)` element is a Call, so the list is not
# literal-evaluable and this file counted as 3 where pytest collects 5.
#
# That is the documented behaviour and not a defect in the script, but the
# under-count is silent in the README table, so the fix belongs at the call
# site. Do not "improve" this back to pytest.param without checking
# `count-queue-cases.py --check` still agrees.
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_idempotency_key_does_not_deduplicate(cleat, retry_workflow, blank):
    """Two starts sending the same blank key are two runs, not one.

    The failure this guards is not an inconvenience. A blank key is what a
    client bug produces -- an unset variable, an empty config value -- so the
    requests that would collide are precisely the ones that never asked to be
    deduplicated, and they can come from different callers. The second caller
    would receive the first caller's run id and a 200 saying it already
    started.
    """
    (status_a, first), (status_b, second) = start_twice(cleat, retry_workflow, blank, blank)

    assert status_a == 201, f"first start rejected: {status_a} {first}"
    assert status_b == 201, (
        f"the second start with a blank key ({blank!r}) answered {status_b}, not 201. "
        f"200 means it was deduplicated against the first: {second!r}. A blank "
        "identifier became a real one, so two unrelated requests that both failed "
        "to set the header now share a run."
    )
    assert run_id(second) != run_id(first), (
        f"both starts returned run {run_id(first)!r} for a blank key {blank!r}. "
        "The second caller was handed the first caller's workflow."
    )
    assert second.get("already_started") is None, (
        f"the second start reports already_started={second.get('already_started')!r}, "
        f"so cleat considered {blank!r} a key it had seen before"
    )


def test_a_real_idempotency_key_still_deduplicates(cleat, retry_workflow):
    """The control, without which the test above proves nothing.

    Every assertion in this file is of the form "these two starts are separate
    runs". An engine whose deduplication was broken outright -- or a client
    helper that dropped the header -- satisfies all of them. This is the case
    that must come out the other way, and it is the reason the blank result can
    be read as "blank is treated as absent" rather than "nothing deduplicates".

    `test_queues.py::test_the_same_idempotency_key_starts_one_run` asserts the
    same thing more thoroughly, including that the body did not run twice. This
    is here anyway: a control in another module is one someone can delete
    without seeing what it was holding up.
    """
    idem = f"idem-{uuid.uuid4().hex[:8]}"
    (status_a, first), (status_b, second) = start_twice(cleat, retry_workflow, idem, idem)

    assert status_a == 201, f"first start rejected: {status_a} {first}"
    assert status_b == 200, (
        f"a repeated start with a real key answered {status_b}, not 200: {second!r}. "
        "Deduplication is not working at all, which would make every other "
        "assertion in this file vacuous."
    )
    assert run_id(second) == run_id(first), (
        f"a repeated real key started a different run: {run_id(first)!r} then "
        f"{run_id(second)!r}"
    )


def test_whitespace_around_a_key_is_not_part_of_it(cleat, retry_workflow):
    """A padded key and a bare key are the same key -- which shows the mechanism.

    This is the test that explains the file. It is not upstream's assertion and
    it is not a property cleat implements; it is the evidence for WHY the blank
    cases above pass.

    `"  k  "` and `"k"` deduplicating together can only happen if the padding
    was stripped before either reached the store, and nothing in cleat strips
    it -- the handler reads the header verbatim and the store's guard is a bare
    emptiness test. It is Go's `net/textproto`, which trims header values while
    parsing the request. That is also exactly why `"   "` arrives as `""`.

    If this ever fails while the blank cases still pass, the trimming moved or
    went away and the blank cases are being carried by something else, which is
    worth knowing before trusting them.
    """
    bare = f"pad-{uuid.uuid4().hex[:8]}"
    (status_a, first), (status_b, second) = start_twice(
        cleat, retry_workflow, f"  {bare}  ", bare
    )

    assert status_a == 201, f"first start rejected: {status_a} {first}"
    assert status_b == 200 and run_id(second) == run_id(first), (
        f"`'  {bare}  '` and `'{bare}'` started different runs "
        f"({status_b}, {second!r}), so header values are no longer being trimmed "
        "on the way in. The blank-key cases in this file pass BECAUSE of that "
        "trimming -- re-derive why they still pass before trusting them."
    )


def test_a_retry_is_told_the_same_thing_whatever_became_of_the_run(
    cleat, retry_workflow, dead_letter_workflow
):
    """The dedup returns the right RUN. It does not return the right ANSWER.

    An idempotency key exists so a caller that lost a response can retry
    safely. The retry is told *the work is already under way, here is its id* --
    and that sentence is identical whether the run is still going, finished, or
    dead-lettered. Three outcomes, three different next actions for the caller,
    one response.

    The consequence worth stating: **a client that treats `already_started` as
    success reports a dead-lettered workflow as succeeded.** Nothing in the
    response contradicts that reading, and the caller has to make a second
    request to find out otherwise.

    Not a claim that the dedup is wrong. It returns the right id -- the sibling
    test above pins that -- and the key row carries a 7-day expiry, which is a
    sensible retry window. This is about what the response says about the run
    it names.

    Cheaper to fix than it looks: `idempotency_keys` already has an `error_msg`
    column, written on the failure path, so for the dead-lettered half the
    information is already in the row the retry looks the key up in. The
    success half is different -- cleat#1049 dropped `idempotency_keys.result`
    and the success path deliberately writes no idempotency row -- so a
    *result* would need storage that was removed on purpose, while a *status*
    or the stored *error* would not. cleat#1151.
    """
    ok_key = f"idem-ok-{uuid.uuid4().hex[:8]}"
    status, started = cleat.start(retry_workflow, {
        "service": "flaky", "key": f"idem-ok-{uuid.uuid4().hex[:8]}",
        "attempts": 1, "intervalMs": 100, "failTimes": 0, "failStatus": 0,
    }, idempotency_key=ok_key)
    assert status == 201, f"start rejected: {status} {started}"
    settled = cleat.await_terminal(started["id"], timeout=60.0)
    assert settled["status"] == "done", (
        f"the control run did not succeed ({settled['status']!r}), so the "
        f"comparison below would be between two failures rather than between a "
        f"success and a failure: {settled!r}"
    )
    _, after_success = cleat.start(retry_workflow, {
        "service": "flaky", "key": "ignored", "attempts": 1, "intervalMs": 100,
        "failTimes": 0, "failStatus": 0,
    }, idempotency_key=ok_key)

    dl_key = f"idem-dl-{uuid.uuid4().hex[:8]}"
    status, dl_started = cleat.start(dead_letter_workflow, {
        "service": "flaky", "key": f"idem-dl-{uuid.uuid4().hex[:8]}",
        "attempts": 2, "intervalMs": 100,
    }, idempotency_key=dl_key)
    assert status == 201, f"start rejected: {status} {dl_started}"

    deadline = time.time() + 90.0
    dl_status = None
    while time.time() < deadline:
        code, body = cleat.api(f"/api/workflows/{dl_started['id']}")
        dl_status = body.get("status")
        if dl_status in ("dead_lettered", "failed"):
            break
        time.sleep(0.5)
    assert dl_status in ("dead_lettered", "failed"), (
        f"the failing run settled as {dl_status!r}; this test needs a run that "
        f"did NOT succeed for the comparison to mean anything"
    )
    _, after_failure = cleat.start(dead_letter_workflow, {
        "service": "flaky", "key": "ignored", "attempts": 2, "intervalMs": 100,
    }, idempotency_key=dl_key)

    # Both retries must at least name the run they joined -- that half works.
    for label, resp in (("success", after_success), ("failure", after_failure)):
        assert resp.get("already_started") == "true", (
            f"the {label} retry did not report already_started: {resp!r}"
        )
        assert resp.get("workflow_id"), (
            f"the {label} retry named no run: {resp!r}"
        )

    same_shape = set(after_success) == set(after_failure)
    if same_shape:
        pytest.skip(
            f"cleat#1151: a retry is told the same thing whichever way the run "
            f"went. After a run that reached 'done' the response carried "
            f"{sorted(after_success)}; after one that reached {dl_status!r} it "
            f"carried {sorted(after_failure)} -- the same fields, so the caller "
            f"cannot tell a completed run from a dead-lettered one without a "
            f"second request.\n"
            f"\n"
            f"A skip rather than a failure while #1151 is open, and every "
            f"assertion above still ran: both retries deduplicated, both named "
            f"a run, and the two runs genuinely reached different terminal "
            f"states -- which is what makes the identical response a finding "
            f"rather than a coincidence."
        )

    assert set(after_success) != set(after_failure), (
        f"the responses are indistinguishable: {after_success!r} vs "
        f"{after_failure!r}"
    )
