# What may live in this repository

This repo is Apache-2.0 and public. Both facts constrain what can be committed
here, and the constraints are not stylistic — getting them wrong creates a real
licensing defect in a public repository.

## The three cases

### 1. Permissive upstream (MIT, Apache-2.0, BSD, ISC) — port it here

Write cleat code that makes the same assertions the upstream test makes. Record
the upstream project, license, and commit in the port's `UPSTREAM` file, and add
the project to the top-level `NOTICE`.

Do **not** vendor upstream source into this repo, even permissively licensed
source. A port is cleat code; the upstream is the specification it was written
against. Keeping it that way means `NOTICE` attribution is the whole of the
obligation, and there is no second license text to track.

### 2. Copyleft upstream (AGPL, GPL, LGPL) — fork it, separately

Real applications worth testing against are often AGPL — `PeerDB-io/peerdb` and
`flexprice/flexprice` both are. These are valuable: PeerDB in particular carries
recorded-history replay fixtures, which is exactly the property cleat's
WASM-versioned replay model needs to demonstrate.

Port them in a **GitHub fork** under `cleat-team/`, created with the fork button
so upstream history and the upstream license travel with it and you can rebase
onto upstream later. The fork stays AGPL. Note that a public fork on GitHub *is*
distribution, so the AGPL obligations are live — that is fine and expected for a
fork, but it is exactly why none of that code may be copied into this repo or
into `cleat-team/cleat`.

**No copyleft-licensed code, in any quantity, in this repository.**

### 3. Upstream with no LICENSE file — do not fork it at all

`temporalio/features` is the case that matters here. It is the single best
conformance corpus in the durable-execution ecosystem: roughly 100 scenario
directories, each holding a plain-English behavioural spec in `README.md`
alongside a small workflow and its expected result, covering signals, child
workflow cancellation modes, continue-as-new, timers, queries, updates,
schedules, and history-replay compatibility.

It also has no `LICENSE` file, which under default copyright means all rights
reserved.

So: do not fork it, and do not copy from it. Read the per-feature `README.md`
specs — which describe publicly documented Temporal behaviour — and implement
equivalent scenarios from scratch in `cleat-team/cleat` under
`tests/conformance/`, where they gate every merge. Record the derivation in
`docs/conformance-provenance.md` in that repo.

That work belongs in core, not here, because it is original cleat code that
you own and that must block merges.

## Checklist before opening a PR that adds a port

- [ ] Upstream `LICENSE` file exists and is MIT, Apache-2.0, BSD, or ISC
- [ ] `ports/<name>/UPSTREAM` records project, URL, license, and pinned commit
- [ ] Top-level `NOTICE` names the upstream project and its copyright holder
- [ ] No upstream source files are vendored — only cleat code you wrote
- [ ] Port's `README.md` states which upstream tests it covers and which it skips
