# Promoting a port finding into core

A port's job is discovery. A finding is only *protected* once it is a hermetic
test in `cleat-team/cleat` that blocks merges. This is that handoff.

The model is `examples/saga-temporal-port/` in the core repo: roughly 250 lines
of ported workflow produced six concrete API findings — a `DurableDefer` that
takes a string rather than a closure, a missing `DurableCallTypedWithOptions`,
a nil-result unmarshal bug in `DurableCallJSONWithOptions`, saga compensation
that silently drops errors, no per-call `StartToCloseTimeout`, and divergent
error wrapping. That yield per line is why this repo exists. What that example
did *not* do is convert those findings into gating tests — which is why this
checklist does.

## Steps

1. **Record it in the port's `ISSUES.md`.** Follow the format in
   `ports/TEMPLATE/ISSUES.md`: what the upstream test asserts, what cleat did,
   and whether it is a bug, a missing API, or an intentional design difference.

2. **Classify it.** Only two of the three classes get promoted:

   | Class | Promote? | Where it goes |
   |---|---|---|
   | Bug — cleat violates a durability guarantee | **yes** | `tests/conformance/` regression test + core issue |
   | Missing API — the behaviour is unreachable | **yes** | Core issue first; test lands with the API |
   | Design difference — cleat is deliberately different | no | Stays in `ISSUES.md`; consider a note in `docs/migration/from-*.md` |

   Be honest about the third row. "Cleat is deliberately different" is a real
   and frequent answer, and inflating it into a bug wastes core's review budget.
   But it is also the comfortable answer, so state *why* the difference is
   deliberate, not just that it is.

3. **Reduce it to a hermetic test.** The core test must not need this repo, the
   upstream framework, a network, or a fixture larger than it needs. It should
   fail on the cleat commit that has the defect and pass on the fix. If you
   cannot make it hermetic, say so in the core issue rather than shipping a
   flaky gate — `tier1-gate.yml` takes no known-failure list, and widening it to
   accommodate a failure is the one change that would make it worthless.

4. **Open the core PR.** Test under `tests/conformance/`, referencing the port
   and the upstream test by name in a comment. Cite the upstream *behaviour*,
   never paste upstream code.

5. **Close the loop here.** Mark the `ISSUES.md` entry with the core issue or PR
   number and its resolution date. A finding with no link is not yet promoted.

## When a port may go stale

Once every finding in a port's `ISSUES.md` is either promoted or classified as a
design difference, the port has done its job. Leave it running in nightly if it
is cheap; retire it if it is not. Do not treat a stale port as a failure — the
protection lives in core now.

The failure mode to actually watch for is the opposite one: a port that keeps
finding things and never promotes them.
