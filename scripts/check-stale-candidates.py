#!/usr/bin/env python3
"""No case `docs/next-upstream.md` still calls a candidate is already adjudicated.

WHY THIS EXISTS
---------------
`scripts/check-worklist-totals.py` reconciles that document's remaining-work
TABLE against its evidence. The prose below the table is not reconciled by
anything, and on 2026-09-17 one of its two live candidates had been dead for
three hours:

  * `TestSelectorNoBlock` was presented as "the stronger of the two" candidate
    gaps, resting on `grep -rli selector ports/*/tests/` returning nothing;
  * ports#237 had landed `ports/samples-go/tests/selector_test.go` at
    2026-09-16T00:44:31Z, covering the surface AND recording that the case is
    not portable -- its workflow uses `workflow.Go`, two channels,
    `AddDefault`, `HasPending` and an activity, of which cleat has none;
  * the document was edited at 03:38:24Z, nearly three hours later, and the
    candidate section was not touched.

A candidate that outlives its own refutation sends the next person to do work
that is done, and to port a case this repository has already established cannot
be ported. That is the same failure the worklist check exists to prevent,
arriving through prose instead of through a number.

WHAT THIS ASSERTS
-----------------
For every upstream case name the document marks as a live candidate -- a table
row whose verdict cell contains "candidate gap" -- no file under
`ports/*/tests/` mentions that name. A port test that names an upstream case has
adjudicated it: ported, refuted, or superseded. Any of the three makes the
candidate stale.

WHY MENTION AND NOT SOMETHING CLEVERER. A mention is the weakest signal that is
still decisive: a port test does not name an upstream case idly, and the three
outcomes are indistinguishable from outside the file anyway. Asking whether the
case was ported rather than refuted would require parsing intent, and would fail
open in the direction that matters -- ports#237 REFUTED the case, and a check
that only looked for ports would have passed it.

MEASURED BEFORE BEING WRITTEN. 62 distinct `Test*` names appear in the document;
7 are mentioned by a port test; 6 of those 7 are already recorded as ported or
already-asserted, and exactly one -- `TestSelectorNoBlock` -- was still marked a
candidate. So this guard fires on one case today and on nothing else, which is
what makes it a guard rather than a filter.

EXIT STATUS
-----------
    0   no live candidate is adjudicated
    1   a candidate is stale -- the document must be updated
    2   could not establish what was being measured

2 is separate from 1 because "the document has no candidate rows" and "there are
no port tests" both agree with every tree, correct or not. See CLAUDE.md in
cleat core on giving "I could not look" its own exit status.
"""

import pathlib
import re
import sys

DOC = pathlib.Path("docs/next-upstream.md")
PORTS = pathlib.Path("ports")
CASE_RE = re.compile(r"`(Test[A-Za-z0-9_]+)`")


def candidate_rows(text):
    """Table rows whose verdict marks a LIVE candidate.

    A withdrawn row says so in the same cell, so the marker has to be read
    together with its negation -- otherwise withdrawing a candidate by
    annotating it would leave this guard firing forever and the only way to
    silence it would be to delete the history.
    """
    out = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        low = line.lower()
        if "candidate gap" not in low:
            continue
        if "withdrawn" in low or "~~" in line:
            continue
        for name in CASE_RE.findall(line):
            out.setdefault(name, line.strip())
    return out


# A synthetic table exercising both arms of candidate_rows(). It runs on EVERY
# invocation rather than behind a flag: a self-test CI has to remember to call
# is a comment, and this one costs microseconds. It also closes the vacuity
# hole -- a document with zero candidate rows is a legitimate state (everything
# triaged), so it must not be an error, but then a parser that silently stopped
# matching would produce the same clean run. This makes "the parser works" a
# fact rather than an assumption, independently of what the document says today.
KNOWN_POSITIVE = """
| case | verdict |
|---|---|
| **`TestLiveOne`** | **candidate gap** — see below |
| ~~**`TestStruckOut`**~~ | **candidate gap**, WITHDRAWN 2026-09-01 |
| **`TestSaidWithdrawn`** | **candidate gap** — WITHDRAWN, superseded |
| `TestNotACandidate` | not portable — asserts on history |
"""


def self_check():
    got = set(candidate_rows(KNOWN_POSITIVE))
    want = {"TestLiveOne"}
    if got != want:
        print(f"UNMEASURED: the candidate-row parser failed its own known-positive: "
              f"found {sorted(got)}, want {sorted(want)}.", file=sys.stderr)
        print("This is a failure of the check, not a finding about the tree.", file=sys.stderr)
        return False
    return True


def port_test_files():
    return sorted(p for p in PORTS.glob("*/tests/*") if p.is_file())


def main():
    if not self_check():
        return 2
    if not DOC.is_file():
        print(f"UNMEASURED: {DOC} not found, so no comparison was made.", file=sys.stderr)
        print("This is a failure of the check, not a finding about the tree.", file=sys.stderr)
        return 2
    files = port_test_files()
    if not files:
        print("UNMEASURED: no files under ports/*/tests/, so no comparison was made.", file=sys.stderr)
        print("This is a failure of the check, not a finding about the tree.", file=sys.stderr)
        return 2

    text = DOC.read_text(encoding="utf-8")
    cands = candidate_rows(text)
    print(f"live candidates in {DOC}: {len(cands)}")
    print(f"port test files scanned:   {len(files)}")

    blobs = {p: p.read_text(encoding="utf-8", errors="replace") for p in files}
    stale = []
    for name, row in sorted(cands.items()):
        hits = [str(p) for p, b in blobs.items() if name in b]
        if hits:
            stale.append((name, hits, row))

    for name, hits, row in stale:
        print(f"\nSTALE CANDIDATE: {name}")
        print(f"  the document still calls it a candidate:\n    {row[:150]}")
        for h in hits:
            print(f"  but it is adjudicated in: {h}")
    if stale:
        print(f"\nERROR: {len(stale)} candidate(s) outlived their own adjudication. "
              f"Update {DOC} -- withdraw the row (strike it through or say WITHDRAWN "
              f"in the verdict cell) and record what the port test established.",
              file=sys.stderr)
        return 1
    print("OK: no live candidate is already adjudicated by a port test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
