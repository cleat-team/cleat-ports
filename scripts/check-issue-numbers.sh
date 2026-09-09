#!/usr/bin/env bash
# Two entries in a port's ISSUES.md must not share a number, and the sequence
# must not have holes.
#
# WHY THIS IS A GUARD AND NOT A CONVENTION. The numbers are assigned by hand,
# by whoever is writing the entry, from a `tail -1` of the file on their own
# branch. Four sessions write this repo, so two of them routinely hold
# unpushed branches that each took "the next number" from the same base --
# and neither sees the other until merge, at which point git reports no
# conflict at all, because the two entries are appended at different offsets
# with different text.
#
# It happened twice on 2026-09-09, in opposite directions:
#
#   * Two sessions both took 29, from branches cut minutes apart. develop's
#     max was 28 and both were right about that.
#   * The advice given to avoid the first collision was itself wrong: a
#     `grep -c '^## '` counted the file's two TEMPLATE headings, so "the next
#     free number" came out one too high.
#
# The cost is not the number. It is that cross-references are by number --
# tests say "ISSUES.md 26", the README says "ISSUES.md #22" -- so a collision
# silently redirects every reference to whichever entry sorted first.
#
# Usage: scripts/check-issue-numbers.sh [--self-test]
#
# --self-test builds throwaway files containing a known duplicate and a known
# hole and asserts this script REPORTS them. That is a known-positive, and it
# is the one that matters: on a clean tree "no duplicates found" and "the
# check does not work" are the same output.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# numbers_of -- reads an ISSUES.md on stdin, prints one entry number per line.
#
# `^## <digits>.` and nothing else. The file's template section has headings
# `## Template for an entry` and `## N. <one-line summary>`, and both are
# excluded by requiring digits -- which is exactly the distinction the bad
# advice above failed to make. Taking stdin rather than a path means
# --self-test drives this same function rather than a parallel copy of it.
numbers_of() {
  grep -E '^## [0-9]+\.' | sed -E 's/^## ([0-9]+)\..*/\1/'
}

report_file() {
  local path="$1" label="$2" rc=0
  local nums dupes
  nums="$(numbers_of < "$path")"

  if [ -z "$nums" ]; then
    echo "ERROR: $label has no numbered entries. Either the file is empty or the" >&2
    echo "       heading format changed and this guard is now reading nothing --" >&2
    echo "       which would report success forever." >&2
    return 1
  fi

  dupes="$(echo "$nums" | sort -n | uniq -d)"
  if [ -n "$dupes" ]; then
    rc=1
    while read -r n; do
      [ -z "$n" ] && continue
      echo "ERROR: $label has $(echo "$nums" | grep -cx "$n") entries numbered $n:" >&2
      grep -nE "^## $n\." "$path" | sed 's/^/         /' >&2
    done <<< "$dupes"
    echo >&2
    echo "  Two sessions took the same number from the same base. Renumber the" >&2
    echo "  LATER one -- whichever is not yet merged -- and update every" >&2
    echo "  reference to it. References are by number:" >&2
    echo >&2
    echo "      grep -rn 'ISSUES.md $dupes' ports/ docs/" >&2
    echo >&2
  fi

  # Holes. A gap means an entry was deleted or a number was skipped, and a
  # skipped number is the first half of a future collision: the next writer
  # takes max+1 and the gap stays open for someone to "helpfully" fill.
  local max first missing
  max="$(echo "$nums" | sort -n | tail -1)"
  first="$(echo "$nums" | sort -n | head -1)"
  missing="$(comm -23 <(seq "$first" "$max") <(echo "$nums" | sort -n | uniq))"
  if [ -n "$missing" ]; then
    rc=1
    echo "ERROR: $label numbers $first..$max with $(echo "$missing" | wc -l | tr -d ' ') missing: $(echo "$missing" | tr '\n' ' ')" >&2
    echo "  A hole is the first half of a collision: the next writer takes" >&2
    echo "  max+1 and the gap stays open indefinitely." >&2
  fi

  return $rc
}

if [ "${1:-}" = "--self-test" ]; then
  fails=0
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  # Known-positive 1: a duplicate.
  printf '## 1. one\n## 2. two\n## 2. also two\n' > "$tmp/dup.md"
  if report_file "$tmp/dup.md" "dup" 2>/dev/null; then
    echo "SELF-TEST FAIL: a duplicate number was not reported" >&2; fails=1
  fi

  # Known-positive 2: a hole.
  printf '## 1. one\n## 3. three\n' > "$tmp/hole.md"
  if report_file "$tmp/hole.md" "hole" 2>/dev/null; then
    echo "SELF-TEST FAIL: a missing number was not reported" >&2; fails=1
  fi

  # Known-positive 3: the failure mode that makes a guard useless -- a file
  # whose headings this script cannot parse must be an ERROR, not a pass.
  printf '## Template for an entry\n## N. <one-line summary>\n' > "$tmp/none.md"
  if report_file "$tmp/none.md" "none" 2>/dev/null; then
    echo "SELF-TEST FAIL: a file with no numbered entries was accepted" >&2; fails=1
  fi

  # Known-negative 1: contiguous from 1.
  printf '## 1. one\n## 2. two\n## 3. three\n' > "$tmp/ok.md"
  if ! report_file "$tmp/ok.md" "ok" 2>/dev/null; then
    echo "SELF-TEST FAIL: a clean file was reported" >&2; fails=1
  fi

  # Known-negative 2: the template headings must NOT be counted as entries,
  # which is the specific mistake that produced bad advice on 2026-09-09.
  printf '## Template for an entry\n## N. <one-line summary>\n## 1. one\n## 2. two\n' > "$tmp/tpl.md"
  if ! report_file "$tmp/tpl.md" "tpl" 2>/dev/null; then
    echo "SELF-TEST FAIL: template headings were counted as entries" >&2; fails=1
  fi

  [ "$fails" -eq 0 ] && echo "SELF-TEST: 5 cases pass (three known-positive, two known-negative)"
  exit "$fails"
fi

rc=0
found=0
while IFS= read -r f; do
  # ports/TEMPLATE is the skeleton a new port is copied from. Its ISSUES.md
  # has no entries BY DEFINITION, so the empty-file error above would fire on
  # it every run -- and a guard that always fails is a guard people learn to
  # ignore. The exemption is by exact path rather than by "files with no
  # entries", which would re-admit the case the empty-file check exists for:
  # a real port whose headings stopped matching.
  case "$f" in
    ports/TEMPLATE/ISSUES.md) continue ;;
  esac
  found=1
  report_file "$f" "$f" || rc=1
done < <(cd "$REPO_ROOT" && git ls-files 'ports/*/ISSUES.md')

if [ "$found" -eq 0 ]; then
  echo "ERROR: no ports/*/ISSUES.md tracked by git outside the TEMPLATE." >&2
  echo "       This guard is checking nothing." >&2
  exit 1
fi

[ "$rc" -eq 0 ] && echo "OK: no port's ISSUES.md has a duplicate or missing entry number."
exit "$rc"
