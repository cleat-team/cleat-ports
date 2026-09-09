#!/usr/bin/env bash
#
# Open or update the nightly's tracking issue on cleat-team/cleat.
#
# THE ONE THING THIS ADDS OVER THE INLINE VERSION IT REPLACES: when GitHub
# rejects the credential, this says so BY NAME instead of exiting 1 with a raw
# `gh` string. Both render as a red X on the run, and they mean opposite things
# -- a rejected token is a harness problem that implies nothing whatever about
# cleat's behaviour, while a genuine failure here means the report did not
# reach anyone. Telling them apart from the run list is the difference between
# "rotate a secret" and "a port diverged".
#
# The old guard was `if [ -z "${GH_TOKEN:-}" ]`, which asks whether the secret
# is SET. On 2026-09-09 it was set and invalid -- created 2026-09-05, rejected
# with 401 -- so the guard passed and the call failed. That is the same shape
# CLAUDE.md records for database DSNs: "A DSN that is set but does not connect
# looks exactly like one that works. Setting the variable is what stops a test
# skipping. Connecting is a separate question."
#
# NOT MADE NON-FATAL, deliberately. A report that silently skips is worse than
# one that fails loudly: the run goes green and the nightly's findings go
# nowhere with nothing to notice. The failure is kept; only its LABEL is fixed.
#
# Env: GH_TOKEN (a PAT with issues:write on cleat-team/cleat), RUN_URL.
set -uo pipefail

: "${RUN_URL:?RUN_URL must be set}"

# AN ABSENT SECRET IS FATAL TOO, AND THAT IS A CHANGE. It used to print
# `::warning::` and exit 0 -- a report that goes nowhere while the run stays
# green, which is the failure mode this whole change is about. Absent and
# invalid have the same consequence (nobody is told), so they get the same
# treatment; only invalid is a regression, and only absent is deliberate, so
# they get different messages.
#
# Cost of this choice, stated rather than buried: a fork that runs this
# schedule without the secret now gets a red nightly instead of a green one.
# That is the right way round -- its report is not reaching anyone either --
# and the summary rendered by the preceding step is readable regardless.
if [ -z "${GH_TOKEN:-}" ]; then
  echo "::error title=HARNESS: CLEAT_CORE_ISSUE_TOKEN is not set::The nightly cannot file its report on ${CORE_REPO:-cleat-team/cleat} without a cross-repo token, so this failure reached nobody. This is a HARNESS failure and says NOTHING about cleat's behaviour -- the port results are in this job's summary above. Fix: set the CLEAT_CORE_ISSUE_TOKEN secret (a PAT or App token with issues:write on the core repo)."
  exit 1
fi

# Overridable ONLY so the failure classification can be exercised against a
# repo where the call is guaranteed to fail in a known way -- see the
# known-positive runs in this change's PR. The workflow never sets it.
CORE_REPO="${CORE_REPO:-cleat-team/cleat}"
TITLE="cleat-ports nightly failing against develop"

# `gh` reports auth failures on stderr and exits non-zero. Classify by the HTTP
# status it names, matching both forms it emits: the REST wrapper's
# `non-200 OK status code: 401 Unauthorized` (measured 2026-09-09, both in run
# 34340316935 and reproduced locally with a deliberately invalid token) and
# `gh api`'s bare `HTTP 401`.
classify_and_die() {
  err="$1"; what="$2"
  code="$(printf '%s' "$err" | sed -nE 's/.*status code: ([0-9]{3}).*/\1/p; s/.*HTTP ([0-9]{3}).*/\1/p' | head -n1)"
  printf '%s\n' "$err" >&2
  case "$code" in
    401)
      # TWO CAUSES, ONE STATUS CODE, DIFFERENT FIXES -- so the annotation carries
      # the discriminator rather than a guess. A 401 means either the stored
      # secret is not a valid token (most often a trailing newline, from
      # `gh secret set` fed by a file or heredoc) or a real token has expired or
      # been revoked. GitHub's PAT page tells them apart for free: "Never used"
      # means the value in the secret never reached GitHub as this token, so
      # rotating will not help until it is stored with `printf %s`.
      #
      # Recorded because it happened: on 2026-09-09 the annotation would have
      # said "invalid or expired -- rotate it", and the PAT read "Never used".
      # A documented failure mode that cannot be told from its neighbour sends
      # the reader confidently down the wrong branch.
      echo "::error title=HARNESS: CLEAT_CORE_ISSUE_TOKEN was rejected (401)::GitHub rejected the cross-repo token, so the nightly could not file its report on ${CORE_REPO}. This is a HARNESS failure and says NOTHING about cleat's behaviour -- the port results are in this job's summary above. Two causes, and the PAT's own page separates them: if it shows a last-used date the token EXPIRED or was REVOKED, so rotate it; if it shows 'Never used' the stored secret is not the token -- usually a trailing newline -- so re-store it with 'printf %s <token> | gh secret set CLEAT_CORE_ISSUE_TOKEN'. Confirm either way with 'GH_TOKEN=<token> gh api user'."
      ;;
    403)
      echo "::error title=HARNESS: CLEAT_CORE_ISSUE_TOKEN lacks permission (403)::The token authenticated but may not write issues on ${CORE_REPO} (missing issues:write, or SSO not authorised for the org). This is a HARNESS failure and says NOTHING about cleat's behaviour -- the port results are in this job's summary above."
      ;;
    *)
      echo "::error title=Could not file the nightly report on ${CORE_REPO}::${what} failed${code:+ with HTTP ${code}}. The port results are in this job's summary above."
      ;;
  esac
  exit 1
}

# One tracking issue, reused. A fresh issue per nightly would bury the core repo
# in duplicates within a week of any sustained failure.
if ! EXISTING=$(gh issue list --repo "$CORE_REPO" --state open \
      --search "\"$TITLE\" in:title" --json number --jq '.[0].number // empty' 2>&1); then
  classify_and_die "$EXISTING" "searching for the tracking issue"
fi

if [ -n "$EXISTING" ]; then
  if ! out=$(gh issue comment "$EXISTING" --repo "$CORE_REPO" \
        --body "Still failing: $RUN_URL" 2>&1); then
    classify_and_die "$out" "commenting on ${CORE_REPO}#${EXISTING}"
  fi
  echo "commented on ${CORE_REPO}#${EXISTING}"
  exit 0
fi

BODY=$(printf '%s\n' \
  "The [cleat-ports](https://github.com/cleat-team/cleat-ports) nightly suite failed against \`develop\`." \
  "" \
  "Run: $RUN_URL" \
  "" \
  "The per-leg breakdown -- which port, which dialect, which cleat SHA -- is in that run's \`Report to core\` job summary. It is rendered from the run's own artifacts and needs no credentials, so it is readable even when this issue is not filed." \
  "" \
  "These are ports of other durable-execution frameworks' test suites. A failure here means cleat's behaviour diverged from what an equivalent engine's tests expect - it is not automatically a bug, but it is always worth a look." \
  "" \
  "Triage per [promotion-checklist.md](https://github.com/cleat-team/cleat-ports/blob/develop/docs/promotion-checklist.md): confirm it, classify it as bug / missing API / deliberate difference, and if it is one of the first two, land a hermetic regression test in \`tests/conformance/\`." \
  "" \
  "_Filed automatically by cleat-ports nightly. This issue is reused rather than duplicated; check the latest comment for the most recent run._")

if ! out=$(gh issue create --repo "$CORE_REPO" --title "$TITLE" --body "$BODY" 2>&1); then
  classify_and_die "$out" "creating the tracking issue"
fi
printf '%s\n' "$out"
