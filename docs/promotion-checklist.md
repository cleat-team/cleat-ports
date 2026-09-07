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
   | Bug — cleat violates a durability guarantee | **yes** | regression test in the package it guards + core issue |
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

4. **Open the core PR.** The gating test goes in **the package it guards** —
   `engine/`, `wasm/`, `auth/`, `cmd/cleat-worker/` — beside the code it
   protects. Reference the port and the upstream test by name in a comment.
   Cite the upstream *behaviour*, never paste upstream code.

   This step used to name a `tests/conformance/` directory. That directory was
   never created, and all nineteen findings to date shipped their regression
   test beside the code instead. Decided 2026-09-07 to describe what happens
   rather than keep asking for what does not: a test next to its subject is
   found when that subject is edited, and several of these are white-box —
   `wasm/adapter_callback_param_test.go` reads `adapterDefs` directly and could
   not live in a separate tree at all.

   What a separate tree would have given is one place to see every guarantee a
   port established. That is the port's `ISSUES.md`, which names the core PR for
   each finding — so the index exists, it is just not a directory.

5. **Close the loop here.** Mark the `ISSUES.md` entry with the core issue or PR
   number and its resolution date. A finding with no link is not yet promoted.

## When a port may go stale

Once every finding in a port's `ISSUES.md` is either promoted or classified as a
design difference, the port has done its job. Leave it running in nightly if it
is cheap; retire it if it is not. Do not treat a stale port as a failure — the
protection lives in core now.

The failure mode to actually watch for is the opposite one: a port that keeps
finding things and never promotes them.
