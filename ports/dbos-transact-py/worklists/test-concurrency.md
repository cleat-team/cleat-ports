## `tests/test_concurrency.py` — 11 cases, read at `833794f7`

**ISSUES.md 22 had already surveyed this file**, and the grep that found it took
one command. The entry classifies nine of the eleven as unportable in principle
— `asyncio.gather` inside a single workflow, which cleat's determinism analyzer
refuses at build time rather than at run time (E001/E002/E012/E013) — and names
the remaining two as "the work-list for this file".

So this section is not a survey. It is the two cases entry 22 left, read and
disposed of.

| upstream case | disposition |
|---|---|
| `test_concurrent_workflows` | **ported** — `test_identity_isolation.py` |
| `test_concurrent_getevent` | open, see below |

### `test_concurrent_workflows`, and why it is not the smoke test it looks like

Ten workflows started from a thread pool, each under a caller-supplied id, each
returning its own. Read quickly it asserts "ten workflows finish". The
assertion that carries it is `assert id == future.result()` — **each run
returns ITS OWN id** — and that is the only case in the file that would catch a
host handing a running workflow somebody else's identity.

cleat is where that is most expressible. One worker runs many workflows at
once, each is a WASM instance the host drives, and `RunID()` is answered out of
host state rather than out of anything the guest holds. A pooled instance, a
reused context, or an index into a slice of in-flight runs all produce the same
symptom: **ten workflows that complete perfectly and report the wrong
identity.**

Two things the port adds that upstream does not have:

- **An overlap assertion.** Ten sequential 1.5s runs satisfy every identity
  assertion while demonstrating nothing about concurrency, and nothing in the
  output would say so. The test measures wall time and requires it under half
  the serial cost.
- **Per-run pairing rather than set equality.** Asserting the ten returned ids
  equal the ten started ids is weaker and a full permutation satisfies it: a
  host that gave every run its neighbour's identity returns exactly the right
  *set*. The test compares each run against the id it was started under.

Falsified by doctoring the workflow to return a constant instead of `RunID()`:
10 of 10 mismatched, **and all ten runs still reached `done`** — which is the
test's own claim about what a completion-only check cannot see.

### `test_concurrent_getevent` — open

Two threads call `get_event` on the same run and event name while a third runs
the workflow that sets it; both readers must receive the same value. cleat's
nearest surface is signals and promises rather than a keyed event map, and
`test_promises.py` / `test_signals.py` cover single-reader delivery. **Whether
two concurrent readers of one promise both observe it is untested here**, and
it is a real question rather than a mechanical port — ISSUES.md 28 records that
a workflow's readers are all keyed, so the shape of the upstream assertion may
not have an analogue at all. Left open deliberately rather than ported badly.

Upstream's final line, `assert not dbos._sys_db.workflow_events_map._dict`,
asserts on SDK internals and has no counterpart in any engine.

### Where this leaves the file

11 upstream cases: 9 unportable in principle (ISSUES 22), 1 ported here, 1
open. **The ceiling is 2, and it is now 1 of 2.** As with `test_queue.py` and
`test_workflow_management.py`, the coverage column is a ceiling and not a
backlog.

---
