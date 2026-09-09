# Contributing

## Adding a port

Read [docs/licensing.md](docs/licensing.md) first — it decides whether an
upstream belongs in this repo at all — then follow
[docs/adding-a-port.md](docs/adding-a-port.md).

## Recording a finding

Findings go in the port's `ISSUES.md`, and are promoted to core per
[docs/promotion-checklist.md](docs/promotion-checklist.md). A finding that stays
only in this repo protects nothing: `cleat-team/cleat`'s `tier1-gate.yml` is what
blocks merges, and this repo cannot.

**Take the entry number at merge time, not at write time.** Several sessions
work this repo at once and each holds unpushed branches, so "the next number"
computed from your own base is a number somebody else is also using. Neither
branch conflicts — the entries land at different offsets with different text —
and the collision only shows up in the cross-references, which are by number
(`ISSUES.md 26`). Before pushing:

```sh
git fetch origin
git show origin/develop:ports/<port>/ISSUES.md | grep -E '^## [0-9]+\.' | tail -1
gh pr list --state open --search 'ISSUES'      # someone may hold the next one
```

`scripts/check-issue-numbers.sh` enforces this in CI and will tell you which
two entries collided. It also rejects **holes**: a skipped number is the first
half of the next collision. Note that the file's two `## Template …` headings
are not entries — counting them is how one of the two collisions on 2026-09-09
was caused by the advice given to prevent the other.

## Merging

`develop` uses a **merge queue**, so do not rebase a pull request by hand to
clear a `BEHIND` state. Add it to the queue and GitHub tests it against the
projected tip — this branch plus everything ahead of it in the batch — then
merges it. Batch size is 5.

**That rule covers staleness and not conflict, and `mergeStateStatus` will not
tell you which you have.** It mixes staleness, conflict and admission into one
field, which is exactly why the two get conflated. The discriminator is
`mergeable`:

| `mergeable` | `mergeStateStatus` | what to do |
|---|---|---|
| `MERGEABLE` | `BEHIND` | queue it; the queue rebases |
| `CONFLICTING` | `DIRTY` | rebase by hand; the queue cannot help |

A PR can read `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN` **while its queue
entry reads `UNMERGEABLE`**, and both are correct: the PR fields answer against
`develop` as it is now, the queue entry answers against the projected tip. So
`CLEAN` does not mean the queue will take it, and nothing in the PR view hints
that a second base exists. **Sample the queue entry's own `state`**, not the
PR's.

This is not "the PR fields lag". **The PR view has no representation for the
queue's question at all**, so a watcher polling them is not reading a stale
answer — it is answering a different question, and no amount of patience
converges. Three PRs in genuinely different states render identically:

| PR | actually | `mergeable` | `mergeStateStatus` | queue entry |
|---|---|---|---|---|
| #107 | stuck | `MERGEABLE` | `CLEAN` | `UNMERGEABLE` |
| #110 | progressing | `MERGEABLE` | `CLEAN` | `AWAITING_CHECKS` |
| #109 | never queued | `MERGEABLE` | `CLEAN` | *absent* |

A watcher gating on the first three columns sampled one of these ninety times
and timed out. It never reported a false green — it gated on `state == MERGED`
— but it could not tell waiting from stuck, because nothing it was reading
moved.

`mergeable` also returns **`UNKNOWN`** for a while after the base branch moves.
That is "recomputing", not a verdict, and treating it as one is a third way to
read a field that is not answering. `git merge-tree` answers immediately,
locally, and against a tip that does not exist yet — when GitHub says
`UNKNOWN`, stop asking GitHub.

You can ask the projected question before the tip exists:

```sh
git merge-tree --write-tree <head-ahead-of-you> <your-head>   # exit 1 = will conflict
```

That names the conflicting files, so "one more rebase" becomes confirmed and
bounded rather than predicted.

The queue exists because `strict: true` means every merge invalidates every
other open pull request, and this repo took 23 merges in 12 hours on
2026-09-09 with five open PRs stale simultaneously. One of them needed three
manual rebases, each costing a full ~20-minute `All ports` run.

**If the queue ever stalls with checks that never start**, the cause is almost
certainly a required workflow missing its `merge_group:` trigger. A queued
batch runs on `gh-readonly-queue/develop/pr-N-<sha>`, and a workflow that only
triggers on `pull_request` produces nothing there. The queue then waits
forever for a status that cannot arrive, which reads as slowness rather than
as a deadlock. Both required checks — `All ports` and `Validate branch name` —
carry the trigger, and `Validate branch name` additionally short-circuits in
queue context because the ref under test is GitHub's own queue branch and
matches no allowed prefix.


## The one rule that is not negotiable

**No copyleft-licensed or unlicensed upstream source enters this repository.**
This repo is public and Apache-2.0, and a violation is a real licensing defect,
not a style problem. Ports are cleat code written against an upstream's
assertions — the upstream is a specification, not a source tree to copy from.

## Conventions

This repo follows the same DCO sign-off and branch-naming conventions as
`cleat-team/cleat`. Sign commits off with `git commit -s`.

**And `-s` really is needed here, which is easy to miss if you also work in
`cleat-team/cleat`.** That repo sets `core.hooksPath=.githooks`, and its hook
adds `Signed-off-by` for you — so a session can land many PRs there without ever
typing `-s` and reasonably conclude sign-off is automatic. A fresh clone of
*this* repo has no `core.hooksPath` and no `.githooks`, so nothing signs for
you. Confirm with:

```sh
git config --get core.hooksPath   # empty here; `.githooks` in cleat-team/cleat
```

Worth stating because the failure is invisible until it happens somewhere else:
the habit that works is the one that was never yours.

**Nothing here enforces it, and this paragraph used to claim otherwise.** It
said "the DCO check fails on the first push". There is no DCO workflow in
`.github/`, no DCO status context, and no DCO check run — the contexts this
repo produces are `All ports`, `dbos-transact-py`, `samples-go`,
`Discover ports` and `Validate branch name`, of which only the first and last
are required. Unsigned commits merge here today.

That correction is the point rather than a footnote. A paragraph written to
warn about an invisible habit — core signs for you, so you conclude signing is
automatic — introduced the same defect one line further down, by promising a
failure that never arrives. Anyone who *tested* the claim learned the opposite
of what it teaches. Found by cleat-agent1-31, whose unsigned #107 passed every
check.

The convention still stands: sign off, because these commits are proposed
upstream to a repo that does enforce it. But it stands on the convention, not
on a gate.

## Branches and merges

Same discipline as `cleat-team/cleat` and `cleat-team/cleat-bench`:

- **`develop` is the default branch.** Open pull requests against it. `main`
  exists but is not where work lands.
- **Branch from `develop`** using a gitflow prefix. The check in
  `.github/workflows/branch-naming.yml` enforces these:

  | prefix | for |
  |---|---|
  | `feature/` | new functionality |
  | `bugfix/` | bug fixes |
  | `fix/` | CI, config, tooling fixes |
  | `docs/` | documentation only |
  | `release/` | release preparation |
  | `hotfix/` | critical production fix |

- **Squash-merge.** Merge commits and rebase merges are disabled on the repo, so
  every PR lands as one commit on `develop` and the branch is deleted
  automatically.

The prefix list follows the core repo rather than cleat-bench, which rejects
`docs/`. The two already disagree and a contributor moving between them hits an
arbitrary difference; see cleat-team/cleat-bench#9.

One practical note, learned the hard way: **renaming a branch closes its open
pull request** rather than retargeting it, and pushing again to a branch that
was already squash-merged and deleted produces a PR whose history conflicts with
`develop`. If you need to rename, open a fresh branch off `develop` and
cherry-pick.

**And there is a silent variant of that, which is worse.** If the pull request
was *closed* but the branch was **not** deleted, a push to it succeeds with no
error, no conflict, and no signal of any kind. The commits are on `origin` and
on no open pull request; nothing is on `develop` and nothing says so. One
session lost a four-minute test with its falsification this way and only learned
of it because someone else went looking.

The remedy is the same -- fresh branch off `develop`, cherry-pick -- but the
detection is not, because there is nothing to detect. **A branch stops being a
workspace the moment its pull request is in someone else's hands.** If you are
adding to work you have already handed over, open a new pull request rather than
pushing to the old branch, and check that the old one is still open before
assuming a successful push means anything.
