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
