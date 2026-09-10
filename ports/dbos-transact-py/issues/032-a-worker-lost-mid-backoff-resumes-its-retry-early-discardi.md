## 32. A worker lost mid-backoff resumes its retry early, discarding the remaining wait

**Class:** Open question — measured, not adjudicated
**Upstream test:** `tests/test_failures.py` — `test_recovery_during_retries`
**Status:** Open — filed upstream as cleat#1111

**What was measured**

Three attempts, a 20s fixed backoff, a fixture that fails once then succeeds.
The only variable is whether the worker is killed during the wait between
attempt one and attempt two.

| | first attempt | second attempt | gap |
|---|---:|---:|---:|
| no crash | 0.5s | 20.1s | **19.6s** |
| worker killed at 0.8s | 0.5s | 12.0s | **11.4s** |

Repeated: 11.4s and 11.5s across two crashed runs. The caller asked for 20s of
spacing between attempts and got roughly 11.5s.

`workflows/retry` sets `BackoffCoefficient: 1.0` and clamps `MaxInterval` to
`InitialInterval`, so the requested spacing is a constant and the comparison is
against one number rather than a series.

**What it appears to be**

The run is reclaimed by the reaper — stale heartbeat plus sweep interval, on
the order of ten seconds — and the retry then fires promptly rather than at the
wake time the policy implied. The remaining backoff is not shortened
proportionally; it is spent by the reclaim delay and whatever is left is
dropped.

**What this entry does NOT claim**

That it is a defect. A case can be made either way and the port is not the
place to settle it:

- *Against*: a backoff exists to space attempts against a dependency that is
  struggling. A crash is exactly when a fleet is most likely to restart many
  workers at once, so collapsing every in-flight backoff to "as soon as
  reclaimed" points a thundering herd at the dependency at the worst moment.
- *For*: the run was already delayed by the reclaim, which is unplanned latency
  the policy did not ask for either, and re-waiting the full interval on top
  would make a crash cost more than the outage it followed.

What is not defensible is that the answer is currently **accidental** — it
falls out of the reclaim interval rather than out of a decision, so it changes
if the reaper's timing changes.

**Why the ported test does not assert it**

`test_a_worker_lost_mid_backoff_resumes_the_retry_rather_than_restarting_it`
asserts completion and the exact call count, both of which hold whichever way
the timing question is answered. Pinning 11.4s would pin the reaper's schedule
into a retry test, and the first person to tune the reaper would have to decide
whether they had broken retries or a measurement of them.

## A second symptom, and the test that was supposed to catch it could not (2026-09-10)

The measurement above is about *timing* — the crash collapses the remaining
wait. There is a second, independent symptom from the same cause, and it is
the more serious one: **the retry budget restarts.**

| | attempts | failTimes | crash | fixture calls |
|---|---:|---:|---|---:|
| control | 3 | 3 | no | **3** |
| probe | 3 | 3 | mid-backoff | **4** |

A three-attempt policy made four calls. `MaxAttempts` bounds attempts per
*incarnation*, not per workflow, so surviving a crash buys the caller a fresh
budget — and for a non-idempotent operation that extra call is a duplicate the
policy explicitly forbade. Both symptoms come from one fact: the host retry
path records nothing on a *failed* attempt (`durablecalls.go:432` fires only on
success), so replay cannot know how much budget is spent.

The timing question is a genuine design decision. This one is not symmetric in
the same way — there is no reading under which a crash should grant more
attempts than the caller authorised.

**`test_a_worker_lost_mid_backoff_resumes_the_retry_rather_than_restarting_it`
asserted exactly this and passed against the defect for its whole life.** It
ran `failTimes=1, attempts=3` and asserted a count of 2. The fixture fails the
first `fail_times` calls *bearing a key* — it counts calls, not attempt
numbers, and it does not restart when the worker does. So the replayed attempt
does not replay its failure; it gets the next call in the sequence, which
succeeds. With f failures and n attempts and one failed call before the crash:

    resuming   -> min(n, f + 1)
    restarting -> 1 + min(n, f)

Equal for every `f < n`. The test's premise — "the fixture fails exactly once,
which makes the count decisive" — named the one property that made the count
useless. Found by another session measuring the engine directly rather than
trusting the port; filed as ports#172 and fixed by setting `f = n`, which costs
the ability to witness a resumed run *succeeding* (that needs its own case).
