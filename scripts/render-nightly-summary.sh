#!/usr/bin/env bash
#
# Render the nightly's per-leg outcome as markdown, from the leg markers alone.
#
# WHY THIS EXISTS. Until now a red nightly's only route to a human was the
# `report` job, which needs CLEAT_CORE_ISSUE_TOKEN -- a cross-repo PAT -- to
# open an issue on cleat-team/cleat. On 2026-09-09 that token was rejected with
# `401 Bad credentials`, so run 34340316935 found a real failure
# (dbos-transact-py on mysql) and told nobody.
#
# The structural part is worse than one expired secret. `report` runs only
# `if: needs.port.result == 'failure'`, so the token is exercised ONLY on the
# nights it is needed. A green night never touches it. Its failure is therefore
# perfectly correlated with the failure it exists to report: it cannot be
# discovered early, because the only thing that would discover it is the thing
# it breaks.
#
# This script needs no token and no network. It answers "did last night's
# nightly find something, and where" from artifacts the run already uploads.
#
# Usage: scripts/render-nightly-summary.sh <dir-of-leg-markers>
set -euo pipefail

dir="${1:?usage: render-nightly-summary.sh <artifact-dir>}"

# Marker format, written by the `port` job:  <port> <dialect> <status> ref=R sha=S
rows=""
total=0
failed=0
unknown=0

for f in "$dir"/*--*; do
  [ -e "$f" ] || continue
  total=$((total + 1))
  line="$(head -n1 "$f")"
  port="$(printf '%s' "$line" | awk '{print $1}')"
  dialect="$(printf '%s' "$line" | awk '{print $2}')"
  status="$(printf '%s' "$line" | awk '{print $3}')"
  build="$(printf '%s' "$line" | awk '{$1=""; $2=""; $3=""; print}' | sed 's/^ *//')"

  # A marker written before the status field existed has `ref=...` in the third
  # column. Reading that as a status would silently score every leg "ref=develop"
  # -- neither pass nor fail, and rendered as though it were an answer.
  case "$status" in
    success|failure|cancelled|skipped) ;;
    *) build="$(printf '%s' "$line" | awk '{$1=""; $2=""; print}' | sed 's/^ *//')"
       status="unknown"; unknown=$((unknown + 1)) ;;
  esac

  case "$status" in
    success) icon="&#9989; pass" ;;
    failure) icon="&#10060; **fail**"; failed=$((failed + 1)) ;;
    *)       icon="&#10067; ${status}" ;;
  esac

  rows="${rows}| \`${port}\` | ${dialect} | ${icon} | ${build:-unrecorded} |
"
done

# VACUITY GUARD. With no markers this would print a clean, empty table -- a
# report that "nothing failed" on a run where nothing ran, which is the exact
# shape the `complete` gate exists to catch one job along. Rendering nothing
# must not read as rendering good news.
if [ "$total" -eq 0 ]; then
  echo "## cleat-ports nightly: NO LEG MARKERS FOUND"
  echo
  echo "\`$dir\` contains no \`<port>--<dialect>\` markers, so this summary"
  echo "covers **zero** legs. That is not a green result -- it means the matrix"
  echo "produced no legs, or the marker artifacts did not upload."
  echo "See the \`Every port ran on every dialect\` job."
  echo "no leg markers in '$dir'" >&2
  exit 1
fi

echo "## cleat-ports nightly: ${failed} of ${total} leg(s) failed"
echo
echo "| port | dialect | result | cleat under test |"
echo "|---|---|---|---|"
printf '%s' "$rows"
echo
if [ "$unknown" -gt 0 ]; then
  echo "> ${unknown} leg(s) reported no outcome. Their markers predate the status"
  echo "> field, or the recording step did not run."
  echo
fi
if [ "$failed" -gt 0 ]; then
  echo "Each failing leg's log is attached to this run as"
  echo "\`log-<port>--<dialect>\`. Triage per"
  echo "[promotion-checklist.md](https://github.com/cleat-team/cleat-ports/blob/develop/docs/promotion-checklist.md):"
  echo "confirm it, classify it as bug / missing API / deliberate difference, and"
  echo "if it is one of the first two, land a hermetic regression test in"
  echo "\`tests/conformance/\`."
elif [ "$unknown" -gt 0 ]; then
  echo "No leg reported a failure, but ${unknown} reported no outcome at all, so"
  echo "this summary cannot say the ports passed -- only that none of them said"
  echo "they failed. Those are different claims."
else
  echo "No leg failed. If this run is red, the failure is in an aggregate job"
  echo "(\`Every port ran on every dialect\`, \`Report to core\`) rather than in a"
  echo "port -- a harness problem, not a divergence from cleat's behaviour."
fi
