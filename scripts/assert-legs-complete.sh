#!/usr/bin/env bash
#
# Fail unless every expected port x dialect leg reported.
#
# WHY THIS IS NOT `needs:`. A job depending on a matrix job succeeds when the
# matrix is EMPTY -- zero legs is zero failures. So an aggregate gating only on
# `needs: port` passes a run that tested nothing, which is the shape cleat#1068
# fixed in the core repo: a job that looks covered while nothing selects it.
#
# It compares SETS, not counts. A count is satisfied by the wrong legs
# reporting -- three postgres legs would satisfy "3 of 3" for a one-port,
# three-dialect matrix.
#
# Usage: PORTS='["a","b"]' DIALECTS='["postgres"]' scripts/assert-legs-complete.sh <dir>
set -euo pipefail

dir="${1:?usage: assert-legs-complete.sh <artifact-dir>}"
: "${PORTS:?PORTS must be a JSON array}"
: "${DIALECTS:?DIALECTS must be a JSON array}"

# A read loop, not `mapfile`: that is bash 4+, and macOS ships 3.2 as
# /bin/bash. Same trap as `declare -A`, and shellcheck does not flag either --
# it assumes a modern bash. GitHub runners have bash 5, so both would have
# worked in CI and failed for anyone reproducing the check locally, which is
# the wrong way round.
ports=(); dialect=()
while IFS= read -r x; do [ -n "$x" ] && ports+=("$x"); done < <(printf '%s' "$PORTS" | jq -r '.[]')
while IFS= read -r x; do [ -n "$x" ] && dialect+=("$x"); done < <(printf '%s' "$DIALECTS" | jq -r '.[]')

# Vacuity guard. With either list empty the product is empty, every element is
# trivially present, and this script would print success having checked
# nothing -- the precise failure it exists to prevent, one level up.
if [ "${#ports[@]}" -eq 0 ] || [ "${#dialect[@]}" -eq 0 ]; then
  echo "FAIL: discover produced ${#ports[@]} port(s) and ${#dialect[@]} dialect(s)." >&2
  echo "      An empty dimension makes the expected set empty and this check vacuous." >&2
  exit 1
fi

missing=()
present=0
for p in "${ports[@]}"; do
  for d in "${dialect[@]}"; do
    if [ -f "$dir/${p}--${d}" ]; then
      present=$((present + 1))
    else
      missing+=("${p} on ${d}")
    fi
  done
done

expected=$(( ${#ports[@]} * ${#dialect[@]} ))
echo "expected ${expected} leg(s) (${#ports[@]} port(s) x ${#dialect[@]} dialect(s)); ${present} reported"

if [ "${#missing[@]}" -gt 0 ]; then
  echo >&2
  echo "FAIL: ${#missing[@]} leg(s) never reported:" >&2
  for m in "${missing[@]}"; do echo "    ${m}" >&2; done
  echo >&2
  echo "      A leg that does not report did not run. That is invisible to" >&2
  echo "      \`needs:\`, which succeeds on an empty or partial matrix." >&2
  exit 1
fi

# Anything reported that was NOT expected means the two sources have drifted --
# the matrix and this gate are supposed to read the same discover outputs.
for f in "$dir"/*--*; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  found=0
  for p in "${ports[@]}"; do
    for d in "${dialect[@]}"; do
      [ "$name" = "${p}--${d}" ] && found=1
    done
  done
  if [ "$found" -eq 0 ]; then
    echo "FAIL: leg '${name}' reported but is not in the expected set." >&2
    echo "      The matrix and this gate have drifted; both should read discover." >&2
    exit 1
  fi
done

echo "ok: every expected leg reported"
