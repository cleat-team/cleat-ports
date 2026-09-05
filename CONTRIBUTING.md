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
