#!/usr/bin/env bash
#
# The nightly's shared failure classifier: turn a `gh` error into an annotation
# that says WHOSE problem it is.
#
# ONE COPY, SOURCED TWICE, AND THAT IS THE POINT. `file-core-issue.sh` (which
# files the report) and `check-core-credential.sh` (which probes the credential
# without filing anything) must classify identically -- a probe that reports the
# credential healthy in terms the real call would not use is a probe you cannot
# act on. Two copies drift, and they drift silently, because nothing compares
# annotation strings.
#
# Callers set CLASSIFY_CONTEXT to one sentence naming where the reader should
# look next. Sourced, not executed.

# `gh` reports auth failures on stderr and exits non-zero. Classify by the HTTP
# status it names, matching BOTH forms it emits -- and it emits two for the same
# condition, measured 2026-09-09:
#
#   gh issue list    (GraphQL) -> non-200 OK status code: 401 Unauthorized
#   gh issue comment (REST)    -> HTTP 401: Bad credentials
#   gh issue create  (REST)    -> HTTP 401: Bad credentials
#
# A matcher for either alone covers half the calls, and it is the create path --
# the one that runs on the FIRST red night, when no tracking issue exists yet --
# that the more obvious matcher misses.

classify_and_die() {
  err="$1"; what="$2"
  ctx="${CLASSIFY_CONTEXT:-}"
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
      echo "::error title=HARNESS: CLEAT_CORE_ISSUE_TOKEN was rejected (401)::GitHub rejected the cross-repo token for ${CORE_REPO}. ${ctx} This is a HARNESS failure and says NOTHING about cleat's behaviour. Two causes, and the PAT's own page separates them: if it shows a last-used date the token EXPIRED or was REVOKED, so rotate it; if it shows 'Never used' the stored secret is not the token -- usually a trailing newline -- so re-store it with 'printf %s <token> | gh secret set CLEAT_CORE_ISSUE_TOKEN'. Confirm either way with 'GH_TOKEN=<token> gh issue list --repo ${CORE_REPO} --limit 1' -- NOT 'gh api user', which fails for a GitHub App installation token that is otherwise fine."
      ;;
    403)
      echo "::error title=HARNESS: CLEAT_CORE_ISSUE_TOKEN lacks permission (403)::The token authenticated but may not access issues on ${CORE_REPO} (missing issues scope, or SSO not authorised for the org). ${ctx} This is a HARNESS failure and says NOTHING about cleat's behaviour."
      ;;
    *)
      echo "::error title=Could not reach ${CORE_REPO}::${what} failed${code:+ with HTTP ${code}}. ${ctx}"
      ;;
  esac
  exit 1
}
