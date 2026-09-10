#!/usr/bin/env bash
# When an ISSUES entry is REWRITTEN, name every file that cites it.
#
# WHY THIS EXISTS. scripts/check-issue-numbers.sh catches a citation whose
# TARGET is gone -- a number with no entry, or two entries with one number. It
# cannot catch the failure that actually happened on 2026-09-09: an entry that
# still exists, still has its number, and no longer says what four other files
# say it says.
#
# Entry 29 was rewritten three times in one evening. Two paragraphs elsewhere
# in the repo then described a finding the entry no longer contained --
# `worklists/test-workflow-management.md` said propagation "is not" done, and
# `docs/durabletask-go-orchestrations-survey.md` described the cancel path as
# having "no parent_workflow_id traversal". Both were accurate when written.
# Neither is now, and nothing in CI could tell.
#
# They were found by someone remembering to grep for citers before landing the
# rewrite. That is a habit, not a check, and this file is the difference.
#
# WHAT IT CHECKS, AND WHY THE HEADING RATHER THAN THE BODY. A citation
# paraphrases an entry's CLAIM, and the claim lives in the `## N. summary`
# heading and the `**Class:**` / `**Status:**` lines. The body is evidence for
# the claim, and evidence gets corrected constantly -- failing on every body
# edit would make this noise, and noise gets deleted.
#
# So: if a PR changes an entry's heading or its Class/Status, and other files
# cite that entry, this fails and lists them. Touch them, or say in the PR why
# they are still right.
#
# IT OVER-REPORTS, DELIBERATELY. A file that merely MENTIONS a number -- this
# repo's own scripts/check-issue-numbers.sh discusses entry 29 as the historical
# collision it was written for -- is reported alongside files that paraphrase
# the entry's claim. Telling those apart needs judgement, and the two error
# directions are not symmetric: an extra line to dismiss costs a moment, while
# a missed citer is the failure this exists to prevent and is invisible.
#
# On the real entry-29 rewrite it reports nine files, of which one is narrative.
#
# Usage: scripts/check-issue-citations.sh [BASE_REF] [--self-test]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Lines that carry an entry's CLAIM. Everything else is evidence.
# NO line numbers: a reformat that moves a Class line must not read as a
# rewritten claim. Comparing `grep -n` output did exactly that -- it flagged
# an entry whose heading was byte-identical, on the first real run.
# The heading and Class in full; Status only as far as its first word.
#
# Status carries a lifecycle annotation that changes constantly and does not
# change what the entry CLAIMS -- `Open` becoming `Open -- filed upstream as
# cleat#1111` is bookkeeping, and flagging it would train people to ignore this
# check. `Open` becoming `Wontfix` is a different claim and is still caught.
#
# Found on the first real run: without this, a status annotation on entry 32
# reported an entry whose heading was byte-identical.
claim_lines() {
  { grep -E '^## [0-9]+\.|^\*\*Class:\*\*' "$1" 2>/dev/null
    grep -E '^\*\*Status:\*\*' "$1" 2>/dev/null | awk '{print $1, $2}'
  } || true
}

# Files citing entry N, excluding the entry itself. The three spellings in use
# were counted rather than assumed: `ISSUES 29`, `entry 29`, `issues/029`.
# NO \b. `git grep -E` does not support it -- every alternative using it matched
# ZERO files, measured, and a pattern that matches nothing reports "nothing
# cites this entry", which reads as safe to land. That is the same silent
# failure this guard exists to catch, inside the guard.
#
#   ISSUES 29        -> 3 files
#   ISSUES 29\b      -> 0 files
#
# `(^|[^0-9])N([^0-9]|$)` is the portable boundary and is what the self-test
# below pins.
citers_of() {
  local n="$1" self="$2" padded
  padded=$(printf '%03d' "$n")
  git grep -l -iE "(ISSUES\.md [#]?|ISSUES |entry )${n}([^0-9]|\$)|issues/${padded}" \
    -- '*.md' '*.py' '*.go' '*.sh' 2>/dev/null | grep -v "^${self}$" || true
}

self_test() {
  local tmp; tmp=$(mktemp -d)
  printf '## 7. a claim\n\n**Class:** X\n\nbody\n' > "$tmp/a.md"
  printf '## 7. a DIFFERENT claim\n\n**Class:** X\n\nbody\n'  > "$tmp/b.md"
  printf '## 7. a claim\n\n**Class:** X\n\nbody edited\n'     > "$tmp/c.md"
  local pass=0
  # known-positive: the heading changed
  if ! diff <(claim_lines "$tmp/a.md") <(claim_lines "$tmp/b.md") >/dev/null; then pass=$((pass+1)); fi
  # known-negative: only the body changed
  if diff <(claim_lines "$tmp/a.md") <(claim_lines "$tmp/c.md") >/dev/null; then pass=$((pass+1)); fi
  # The CITATION half needs its own known-positive. The first version of this
  # self-test covered only claim extraction, and the citation pattern was
  # broken -- \b matching nothing -- while the self-test reported 2/2.
  printf 'see ISSUES 7 for the rest\n' > "$tmp/cite.md"
  printf 'unrelated, mentions 77 and 7000\n' > "$tmp/nocite.md"
  ( cd "$tmp" && git init -q . && git add -A && git -c user.email=t@t -c user.name=t commit -qm t ) 2>/dev/null
  local found
  found=$( cd "$tmp" && git grep -l -iE "(ISSUES\.md [#]?|ISSUES |entry )7([^0-9]|\$)|issues/007" -- '*.md' 2>/dev/null )
  case "$found" in
    *cite.md*) case "$found" in *nocite.md*) : ;; *) pass=$((pass+1)) ;; esac ;;
  esac
  rm -rf "$tmp"
  if [ "$pass" -ne 3 ]; then
    echo "SELF-TEST FAILED ($pass/3): extractor or citation pattern does not discriminate." >&2
    echo "On a clean tree a broken extractor and a clean repo look identical, which" >&2
    echo "is the whole reason this self-test exists." >&2
    exit 1
  fi
  echo "SELF-TEST: 3 cases pass (claim changed, claim unchanged, citation found and not over-matched)"
}

BASE="${1:-origin/develop}"
[ "${1:-}" = "--self-test" ] && { self_test; exit 0; }
[ "${2:-}" = "--self-test" ] && self_test

git rev-parse --verify -q "$BASE" >/dev/null || {
  echo "check-issue-citations: no such base ref: $BASE" >&2
  echo "Pass one explicitly, e.g. scripts/check-issue-citations.sh origin/develop" >&2
  exit 2
}

# Keyed by entry NUMBER, not by path.
#
# A rewrite usually RENAMES the file, because the filename is derived from the
# heading -- and when the body changes enough, git reports the rename as an
# add plus a delete rather than as R. Keying on paths then compares a file
# against nothing, finds no "before", and skips the entry as newly added.
#
# That is not a hypothetical: entry 29's rewrite is exactly this shape, and it
# is the case this guard was written for. Keying by number makes the rename
# invisible to the comparison, which is what it should be.
changed=$(git diff --name-only "$BASE"...HEAD -- 'ports/*/issues/*.md' 2>/dev/null \
          | xargs -I{} basename {} 2>/dev/null \
          | sed -E 's/^0*([0-9]+).*/\1/' | sort -un)
[ -z "$changed" ] && { echo "OK: no ISSUES entry was rewritten against $BASE."; exit 0; }

# path_for <ref-or-worktree> <port-dir> <number>
path_at() {
  local ref="$1" n="$2" padded; padded=$(printf '%03d' "$n")
  # No pathspec: `ls-tree -- 'ports/*/issues/'` matched nothing here, and a
  # pathspec that silently selects nothing is indistinguishable from an entry
  # that does not exist -- which is how this guard reported OK on the very
  # rewrite it was written for.
  git ls-tree -r --name-only "$ref" 2>/dev/null | grep -E "/issues/${padded}-" | head -1
}

rc=0
for n in $changed; do
  [ -n "$n" ] || continue
  oldpath=$(path_at "$BASE" "$n")
  newpath=$(git ls-files | grep -E "/issues/$(printf '%03d' "$n")-" | head -1)

  [ -z "$oldpath" ] && continue          # newly added entry: nothing cites it yet
  [ -z "$newpath" ] && continue          # deleted: the numbers guard covers that

  tmpb=$(mktemp); git show "$BASE:$oldpath" > "$tmpb" 2>/dev/null
  before=$(claim_lines "$tmpb"); rm -f "$tmpb"
  after=$(claim_lines "$newpath")
  [ "$before" = "$after" ] && continue

  cites=$(citers_of "$n" "$newpath")
  # the entry's own old path is not a citer of itself
  cites=$(printf '%s\n' "$cites" | grep -v "^${oldpath}$" | grep -v '^$' || true)
  [ -z "$cites" ] && continue

  rc=1
  echo "ERROR: entry $n's CLAIM changed and these files cite it:" >&2
  echo "$cites" | sed 's/^/    /' >&2
  echo >&2
  echo "  was: $(printf '%s' "$before" | head -1 | cut -c1-96)" >&2
  echo "  now: $(printf '%s' "$after"  | head -1 | cut -c1-96)" >&2
  [ "$oldpath" != "$newpath" ] && echo "  (the file was renamed, which is itself a changed heading)" >&2
  echo >&2
  echo "  A citation paraphrases the claim, so a rewritten claim can leave a" >&2
  echo "  paragraph that was accurate when written and is not now. Update them," >&2
  echo "  or say in the PR why each is still right. Entry 29 on 2026-09-09 left" >&2
  echo "  two such paragraphs and nothing in CI could see them." >&2
done

[ "$rc" -eq 0 ] && echo "OK: every rewritten entry's citers are accounted for."
exit "$rc"
