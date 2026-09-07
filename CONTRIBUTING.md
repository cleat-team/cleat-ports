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

## The one rule that is not negotiable

**No copyleft-licensed or unlicensed upstream source enters this repository.**
This repo is public and Apache-2.0, and a violation is a real licensing defect,
not a style problem. Ports are cleat code written against an upstream's
assertions — the upstream is a specification, not a source tree to copy from.

## Conventions

This repo follows the same DCO sign-off and branch-naming conventions as
`cleat-team/cleat`. Sign commits off with `git commit -s`.

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
