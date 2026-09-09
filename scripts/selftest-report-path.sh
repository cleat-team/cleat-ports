#!/usr/bin/env bash
#
# Exercise every branch of the nightly's reporting path with a KNOWN-POSITIVE:
# a case already known to be broken, checking that the code says so.
#
# WHY THIS IS CHECKED IN RATHER THAN RUN ONCE BY HAND. Every branch below fires
# only when something is already wrong, so "it passed" proves nothing about any
# of them -- a completely inert classifier passes a green tree. Run-once
# evidence also rots invisibly: while writing this change, adding the
# absent-token branch to file-core-issue.sh silently disabled the negative
# control for case 3, because that case had been relying on `gh`'s stored
# credentials rather than GH_TOKEN. It still exited 1, still printed an
# annotation, and still looked like a pass. Only re-running the whole set
# against stated expectations caught it.
#
# Case 3 is the one that matters most: it is the only case that requires the
# classifier to DISAGREE with the easy conclusion. Everything else asks whether
# a failure is reported; case 3 asks whether a failure that is NOT the token's
# fault is kept off the token.
#
# Usage: scripts/selftest-report-path.sh        (uses `gh auth token` locally)
#        SELFTEST_VALID_TOKEN=... scripts/selftest-report-path.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

BAD_TOKEN="ghp_0000000000000000000000000000000000"
NO_SUCH_REPO="cleat-team/no-such-repo-selftest-xyzzy"
fails=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# `assert` takes what must appear and what must NOT. The second half is not
# decoration: case 3 passes trivially if you only check that it failed.
ck() { # ck <name> <expected-exit> <must-contain> <must-not-contain-or-empty> <output>
  name="$1"; want="$2"; yes="$3"; no="$4"; got="$5"; code="$6"
  bad=""
  [ "$code" = "$want" ] || bad="expected exit $want, got $code"
  case "$got" in *"$yes"*) ;; *) bad="${bad}${bad:+; }missing: $yes" ;; esac
  if [ -n "$no" ]; then case "$got" in *"$no"*) bad="${bad}${bad:+; }must not contain: $no" ;; esac; fi
  if [ -n "$bad" ]; then
    printf 'FAIL  %s\n        %s\n' "$name" "$bad"; printf '        --- got ---\n%s\n' "$got" | head -5
    fails=$((fails + 1))
  else
    printf 'ok    %s\n' "$name"
  fi
}

# A valid token is REQUIRED, not optional. Case 3 without one degrades into
# case 2 and reports a pass, which is the exact substitution this file exists
# to make impossible.
#
# PROBE THE CAPABILITY CASE 3 NEEDS, NOT A PROXY FOR IT. This first read
# `gh api user`, which fails for CI's GITHUB_TOKEN: that is a GitHub App
# INSTALLATION token, and `GET /user` requires user-to-server auth, so the probe
# rejected a token that is perfectly able to do what case 3 does. Asking the
# same question case 3 asks -- can this token list issues -- has no such gap and
# cannot pass a token that would then fail inside the case.
VALID="${SELFTEST_VALID_TOKEN:-$(gh auth token 2>/dev/null)}"
if [ -z "$VALID" ] || ! GH_TOKEN="$VALID" gh issue list --repo cleat-team/cleat-ports \
     --limit 1 --json number >/dev/null 2>&1; then
  echo "FAIL: no VALID token available. Case 3 -- 'a non-auth failure must NOT be" >&2
  echo "      blamed on the token' -- cannot run, and it is the only case here that" >&2
  echo "      requires the classifier to disagree. Set SELFTEST_VALID_TOKEN to a" >&2
  echo "      token that can list issues on cleat-team/cleat-ports." >&2
  exit 1
fi

run() { out=$( "$@" 2>&1 ); rc=$?; }

echo "== scripts/file-core-issue.sh =="
run env GH_TOKEN="$BAD_TOKEN" RUN_URL=https://example/selftest bash scripts/file-core-issue.sh
ck "token set and INVALID -> named a rejected credential" 1 \
   "title=HARNESS: CLEAT_CORE_ISSUE_TOKEN was rejected (401)" "" "$out" "$rc"

run env -u GH_TOKEN RUN_URL=https://example/selftest bash scripts/file-core-issue.sh
ck "token ABSENT -> named a missing credential" 1 \
   "title=HARNESS: CLEAT_CORE_ISSUE_TOKEN is not set" "" "$out" "$rc"

run env GH_TOKEN="$VALID" CORE_REPO="$NO_SUCH_REPO" RUN_URL=https://example/selftest bash scripts/file-core-issue.sh
ck "VALID token, missing repo -> does NOT blame the token" 1 \
   "title=Could not reach" "HARNESS" "$out" "$rc"

echo "== scripts/check-core-credential.sh =="
# The healthy path is probed against THIS repo, not cleat-team/cleat: CI's
# GITHUB_TOKEN is scoped here, and a case that needs cross-repo access would
# fail for a reason that has nothing to do with what it is testing.
run env GH_TOKEN="$VALID" CORE_REPO=cleat-team/cleat-ports bash scripts/check-core-credential.sh
ck "probe, working credential -> passes" 0 "Proved: the secret is a valid credential" "" "$out" "$rc"
ck "probe, working credential -> states what it did NOT prove" 0 \
   "NOT proved: that it can WRITE issues" "" "$out" "$rc"

run env GH_TOKEN="$BAD_TOKEN" bash scripts/check-core-credential.sh
ck "probe, INVALID credential -> named a rejected credential" 1 \
   "title=HARNESS: CLEAT_CORE_ISSUE_TOKEN was rejected (401)" "" "$out" "$rc"

run env -u GH_TOKEN bash scripts/check-core-credential.sh
ck "probe, ABSENT credential -> named a missing credential" 1 \
   "title=HARNESS: CLEAT_CORE_ISSUE_TOKEN is not set" "" "$out" "$rc"

run env GH_TOKEN="$VALID" CORE_REPO="$NO_SUCH_REPO" bash scripts/check-core-credential.sh
ck "probe, VALID token + missing repo -> does NOT blame the token" 1 \
   "title=Could not reach" "HARNESS" "$out" "$rc"

echo "== scripts/render-nightly-summary.sh =="
mkdir -p "$tmp/none"
run bash scripts/render-nightly-summary.sh "$tmp/none"
ck "zero markers -> refuses to read as good news" 1 "NO LEG MARKERS FOUND" "" "$out" "$rc"

mkdir -p "$tmp/mixed"
for p in samples-go dbos-transact-py; do for d in postgres mysql mssql; do
  echo "$p $d success ref=develop sha=1055cfb" > "$tmp/mixed/$p--$d"; done; done
echo "dbos-transact-py mysql failure ref=develop sha=1055cfb" > "$tmp/mixed/dbos-transact-py--mysql"
run bash scripts/render-nightly-summary.sh "$tmp/mixed"
ck "1 of 6 failed -> counts it" 0 "1 of 6 leg(s) failed" "" "$out" "$rc"
ck "1 of 6 failed -> names the leg" 0 "| \`dbos-transact-py\` | mysql | &#10060; **fail** |" "" "$out" "$rc"

mkdir -p "$tmp/old"
echo "samples-go postgres ref=develop sha=1055cfb" > "$tmp/old/samples-go--postgres"
run bash scripts/render-nightly-summary.sh "$tmp/old"
ck "marker with no status -> will not claim the ports passed" 0 \
   "reported no outcome" "No leg failed." "$out" "$rc"

echo
if [ "$fails" -gt 0 ]; then echo "$fails case(s) failed"; exit 1; fi
echo "all cases behaved"
