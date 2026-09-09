#!/usr/bin/env bash
#
# Prove CLEAT_CORE_ISSUE_TOKEN still works, WITHOUT filing anything.
#
# WHY. `report` runs only `if: needs.port.result == 'failure'`, so the token is
# exercised only on the nights the nightly has something to say. A green night
# never touches it, and its failure is therefore perfectly correlated with the
# event it exists to report -- it cannot be discovered early, because the only
# thing that would discover it is the thing it breaks. On 2026-09-09 it was
# rejected with 401, run 34340316935 found a real mysql failure, and nobody was
# told. See cleat-ports#105.
#
# Confirmed the hard way the next morning: a nightly was dispatched specifically
# to learn whether the rotated secret worked, all six legs passed, `report` was
# skipped, and 25 minutes bought no information about the credential at all.
#
# This runs in about fifteen seconds, on every nightly including green ones, and
# on demand via the workflow's credential_only input.
#
# THE CALL IS THE ONE THE REPORT PATH ACTUALLY MAKES, not a proxy for it.
# `gh api user` was the obvious probe and is wrong twice over: it fails for a
# GitHub App installation token that is otherwise perfectly capable, and it
# exercises a REST path whose 401 string differs from the GraphQL one the real
# first call emits. Probing the operation removes both gaps.
#
# Env: GH_TOKEN. Optional CORE_REPO, for the self-test only.
set -uo pipefail

CORE_REPO="${CORE_REPO:-cleat-team/cleat}"
CLASSIFY_CONTEXT="No issue was filed and nothing was changed -- this step only probes the credential."
# shellcheck source=scripts/lib-gh-classify.sh
. "$(dirname "$0")/lib-gh-classify.sh"

if [ -z "${GH_TOKEN:-}" ]; then
  echo "::error title=HARNESS: CLEAT_CORE_ISSUE_TOKEN is not set::The nightly has no credential for ${CORE_REPO}, so a failing night would reach nobody. This is a HARNESS failure and says NOTHING about cleat's behaviour. Fix: set the CLEAT_CORE_ISSUE_TOKEN secret (a PAT or App token with issues:write on the core repo)."
  exit 1
fi

if ! out=$(gh issue list --repo "$CORE_REPO" --limit 1 --json number 2>&1); then
  classify_and_die "$out" "probing the report credential against ${CORE_REPO}"
fi

# SAY WHAT THIS DID NOT PROVE, in the success message, where someone reading a
# green run will see it. The probe reads issues; the report path WRITES them. A
# token that has lost issues:write while keeping issues:read passes here and
# fails on the night it is needed. Closing that gap needs a write, and every
# honest test of a write permission is a write -- so this narrows the window
# rather than shutting it, and must not be quoted as "the credential is checked
# nightly" without the qualifier.
echo "ok: ${CORE_REPO} accepted CLEAT_CORE_ISSUE_TOKEN and returned issues."
echo "    Proved: the secret is a valid credential and can READ issues there,"
echo "            so the 401 class (expired, revoked, malformed secret) is clear."
echo "    NOT proved: that it can WRITE issues. A token with issues:read but not"
echo "            issues:write passes this and still fails on a red night."
