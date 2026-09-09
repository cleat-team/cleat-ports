## 32. A worker lost mid-backoff resumes its retry early, discarding the remaining wait

**Class:** Open question — measured, not adjudicated
**Upstream test:** `tests/test_failures.py` — `test_recovery_during_retries`
**Status:** Open

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
