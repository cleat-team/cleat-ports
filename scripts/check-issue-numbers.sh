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

# report_numbers -- the duplicate and hole checks, on a list of numbers.
# Factored out so the two layouts cannot drift apart: a bug fixed for one
# would otherwise stay live in the other.
report_numbers() {
  local nums="$1" label="$2" rc=0 dupes max first missing
  dupes="$(echo "$nums" | sort -n | uniq -d)"
  if [ -n "$dupes" ]; then
    rc=1
    while read -r n; do
      [ -z "$n" ] && continue
      echo "ERROR: $label has $(echo "$nums" | grep -cx "$n") entries numbered $n" >&2
    done <<< "$dupes"
  fi
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

# report_links checks that every issues/ link in an index RESOLVES and that the
# linked file's heading matches the text the index shows for it.
#
# The number check above compares SETS OF NUMBERS, so it is satisfied by an
# index whose row 29 points at a file that no longer exists under a title that
# is no longer true. That is not hypothetical: renaming entry 29 on 2026-09-09
# left exactly that, and every existing check stayed green -- the number 29 was
# still listed and still present.
#
# Takes an index path and a port directory; prints each problem and returns 1
# if there were any.
report_links() {
  local idx="$1" dir="$2" rc=0 line title target head filetitle
  while IFS= read -r line; do
    title="${line%%$'\t'*}"
    target="${line#*$'\t'}"
    if [ ! -f "$dir/$target" ]; then
      echo "ERROR: $idx links to $target, which does not exist." >&2
      echo "  A renamed entry file leaves the index pointing at the old slug." >&2
      rc=1
      continue
    fi
    head="$(head -1 "$dir/$target")"
    filetitle="$(printf '%s' "$head" | sed -n 's/^##[[:space:]]*[0-9][0-9]*\.[[:space:]]*//p')"
    if [ -n "$filetitle" ] && [ "$filetitle" != "$title" ]; then
      echo "ERROR: $idx and $target disagree about the entry's title." >&2
      echo "  index: $title" >&2
      echo "  file : $filetitle" >&2
      echo "  The index is what people read; a stale row here misdescribes a" >&2
      echo "  finding that has since been corrected." >&2
      rc=1
    fi
  done < <(grep -o '\[[^]]*\](issues/[^)]*\.md)' "$idx" \
             | sed 's/^\[//; s/\](/\t/; s/)$//')
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

  # Known-positive 4: a link that does not resolve.
  mkdir -p "$tmp/p/issues"
  printf '## 1. real title\n' > "$tmp/p/issues/001-real.md"
  printf '| 1 | [real title](issues/001-gone.md) |\n' > "$tmp/p/IDX.md"
  if report_links "$tmp/p/IDX.md" "$tmp/p" 2>/dev/null; then
    echo "SELF-TEST FAIL: a broken issues/ link was not reported" >&2; fails=1
  fi

  # Known-positive 5: a link that resolves to a file with a different title.
  printf '| 1 | [stale title](issues/001-real.md) |\n' > "$tmp/p/IDX.md"
  if report_links "$tmp/p/IDX.md" "$tmp/p" 2>/dev/null; then
    echo "SELF-TEST FAIL: a title disagreeing with its file was not reported" >&2; fails=1
  fi

  # Known-negative 3: a link that resolves with a matching title.
  printf '| 1 | [real title](issues/001-real.md) |\n' > "$tmp/p/IDX.md"
  if ! report_links "$tmp/p/IDX.md" "$tmp/p" 2>/dev/null; then
    echo "SELF-TEST FAIL: a correct index row was reported" >&2; fails=1
  fi

  [ "$fails" -eq 0 ] && echo "SELF-TEST: 8 cases pass (five known-positive, three known-negative)"
  exit "$fails"
fi

# THE UNIVERSE IS PORT DIRECTORIES, NOT ISSUES.md FILES.
#
# This loop used to iterate `git ls-files 'ports/*/ISSUES.md'`, and a port whose
# ISSUES.md stopped existing simply left the universe. Measured 2026-09-09 by
# deleting ports/dbos-transact-py/ISSUES.md: the guard found samples-go's file,
# checked it, found nothing wrong, and reported
#
#     OK: no port's ISSUES.md has a duplicate or missing entry number.
#
# with rc=0, while 32 entries had become invisible to it.
#
# The `found -eq 0` check below did not fire and could not: `found` is zero only
# when NO port anywhere has an ISSUES.md, so a single surviving file masks every
# other port's disappearance.
#
# That is not a resolution problem. No stricter regex and no more careful parse
# reaches a file the loop was never given, so the repair is to change what the
# check RANGES OVER: every directory under ports/ except TEMPLATE must have an
# ISSUES.md, and a port without one is an error rather than an absence.
rc=0
found=0
while IFS= read -r d; do
  case "$d" in ports/TEMPLATE) continue ;; esac
  f="$d/ISSUES.md"
  if [ ! -f "$REPO_ROOT/$f" ]; then
    echo "ERROR: $d has no ISSUES.md." >&2
    echo "       Every port keeps one. If this port's findings moved to a" >&2
    echo "       different layout, this guard has to move with them: it cannot" >&2
    echo "       see a file it does not know to look for, and it reports OK." >&2
    rc=1
    continue
  fi
  found=1

  # Two layouts, and which one a port uses is decided by the tree rather than
  # by a flag: a port with an issues/ directory keeps one entry per file and
  # ISSUES.md is a generated index of them; a port without one keeps every
  # entry appended into ISSUES.md itself. samples-go is still the second kind.
  if [ -d "$REPO_ROOT/$d/issues" ]; then
    # The numbers come from the FILENAMES, which is the whole point of the
    # split -- two sessions adding entries touch different files and cannot
    # collide on the tail of one.
    entries="$(cd "$REPO_ROOT/$d/issues" && ls -1 *.md 2>/dev/null | sed -n 's/^0*\([0-9][0-9]*\)-.*/\1/p')"
    if [ -z "$entries" ]; then
      echo "ERROR: $d/issues exists but holds no NNN-*.md entries." >&2
      rc=1; continue
    fi
    report_numbers "$entries" "$d/issues" || rc=1

    # AND THE INDEX MUST NOT DRIFT. A generated table that quietly stops
    # listing an entry is the same defect as a guard that stops seeing a file:
    # everything downstream reads the index, so an entry missing from it is an
    # entry nobody finds, and nothing else would notice.
    listed="$(sed -n 's#^| *\([0-9][0-9]*\) *| .*(issues/.*#\1#p' "$REPO_ROOT/$f" | sort -n)"
    have="$(echo "$entries" | sort -n)"
    if [ "$listed" != "$have" ]; then
      echo "ERROR: $f does not list exactly the entries in $d/issues/." >&2
      echo "  only in the index:     $(comm -23 <(echo "$listed") <(echo "$have") | tr '\n' ' ')" >&2
      echo "  only in the directory: $(comm -13 <(echo "$listed") <(echo "$have") | tr '\n' ' ')" >&2
      rc=1
    fi
    report_links "$REPO_ROOT/$f" "$REPO_ROOT/$d" || rc=1
  else
    report_file "$REPO_ROOT/$f" "$f" || rc=1
  fi
# NF>2 keeps only paths with something INSIDE a port directory, which is what
# makes this a list of directories rather than of entries under ports/.
# `ports/README.md` is a tracked file directly under ports/ and was reported as
# a port with no ISSUES.md on the first run of this loop.
done < <(cd "$REPO_ROOT" && git ls-files ports | awk -F/ 'NF>2 {print $1"/"$2}' | sort -u)

if [ "$found" -eq 0 ]; then
  echo "ERROR: no port outside TEMPLATE has an ISSUES.md; this guard is checking nothing." >&2
  exit 1
fi

[ "$rc" -eq 0 ] && printf 'OK: every port ISSUES.md has unique contiguous numbers, lists exactly\n    the entries in its issues/ directory, and links to titles that match.\n'
exit "$rc"
