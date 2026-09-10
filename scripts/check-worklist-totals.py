#!/usr/bin/env python3
"""Reconcile next-upstream.md's remaining-work table against its own evidence.

WHY THIS EXISTS
---------------
`docs/next-upstream.md` carries a per-file "portable, unported" column whose
total drives one decision: finish the first upstream, or start a second. On
2026-09-10 that total said **18**. Four of its rows were stale, and every one
was stale in a document the table summarises:

  * `test-client.md`    `### Portable - 3 - **ported 2026-09-09**`
  * `test-scheduler.md` `### Portable - 5 - **all five ported 2026-09-09**`
  * `test-failures.md`  `### Ported since this section was written - 2 of the 5`
  * `test-concurrency.md` resolved its one open case as *not portable*, lower
    down the same file.

None was wrong when written. A hand-maintained total assembled from eight other
documents has no way to notice when one of the eight changes, and this one
outlived four separate updates that each stayed local.

That document's own text says an unenumerated count has nothing to reconcile
against. This is the reconciliation, run as a check rather than remembered.

WHAT IT ASSERTS
---------------
For each row of the table, the number matches what the evidence says:

  * the worklist's own `### Portable - N` heading, and whether that heading is
    annotated as ported;
  * whether each case named in that section is cited by a test in
    `ports/dbos-transact-py/tests/` -- the convention this port already follows,
    a ported test naming its upstream case in its docstring.

It does NOT assert that the remaining count is zero. Real outstanding work is
the normal state; a stale number is the defect.

WHAT IT REFUSES TO DO
---------------------
Skip quietly. A worklist with no recognisable heading, a table row with no
worklist, or a run that parses nothing at all are all reported. A guard whose
silence can mean "found nothing to look at" is worth less than no guard, because
it converts a broken parser into a clean bill of health -- which is the exact
shape of the defect it exists to catch.

Exit codes: 0 reconciled, 1 discrepancy, 2 could not run.
"""

import os
import re
import sys

# The repo root, overridable so the selftest can point this at a built tree.
# Without the override the selftest would have to mutate the real docs, and a
# guard whose test corrupts the thing it guards is not testable at all.
ROOT = os.environ.get("CLEAT_PORTS_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "next-upstream.md")
WORKLISTS = os.path.join(ROOT, "ports", "dbos-transact-py", "worklists")
TESTS = os.path.join(ROOT, "ports", "dbos-transact-py", "tests")

# `| `test_failures.py` | 37 | 5 |` and the `17 -> 9 -> **2**` corrected form.
ROW = re.compile(r"^\|\s*`(test_\w+\.py)`\s*\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*$", re.M)
# The last bolded or bare integer in a cell like "17 -> 9 -> **2**, see below".
LAST_NUM = re.compile(r"(\d+)(?!.*\d)", re.S)
PORTABLE_H = re.compile(r"^###\s+Portable\s*[-—–]\s*(\d+)(.*)$", re.M)
CASE = re.compile(r"`(test_\w+)`")
# "ported", "all five ported", "Ported since this section was written - 2 of the 5"
PORTED_NOTE = re.compile(r"\bported\b", re.I)


def die(msg):
    print(f"check-worklist-totals: {msg}", file=sys.stderr)
    sys.exit(2)


def worklist_for(upstream_file):
    # tests/test_failures.py -> worklists/test-failures.md
    stem = upstream_file[:-3].replace("_", "-")
    return os.path.join(WORKLISTS, stem + ".md")


def main():
    for path in (DOC, WORKLISTS, TESTS):
        if not os.path.exists(path):
            die(f"missing {path} -- run from a checkout of cleat-ports")

    doc = open(DOC, encoding="utf-8").read()
    rows = ROOT_ROWS = ROW.findall(doc)
    if not rows:
        die("parsed 0 rows from next-upstream.md's table; the format changed "
            "and this check is measuring nothing")

    tests_blob = ""
    names = [n for n in sorted(os.listdir(TESTS)) if n.endswith(".py")]
    if not names:
        die(f"no test files under {TESTS}")
    for n in names:
        tests_blob += open(os.path.join(TESTS, n), encoding="utf-8").read()

    findings = []      # provable disagreement -- fails
    unverified = []    # no evidence either way -- reported, does not fail
    checked = 0

    for upstream, _total, claim_cell in rows:
        m = LAST_NUM.search(claim_cell)
        if not m:
            findings.append(f"{upstream}: cannot read a number from cell {claim_cell!r}")
            continue
        claimed = int(m.group(1))

        wl = worklist_for(upstream)
        if not os.path.exists(wl):
            findings.append(f"{upstream}: table row has no worklist at "
                            f"{os.path.relpath(wl, ROOT)}")
            continue

        text = open(wl, encoding="utf-8").read()
        checked += 1

        heads = PORTABLE_H.findall(text)
        if not heads:
            # No `### Portable - N`. Only acceptable when the row claims 0.
            if claimed != 0:
                unverified.append(
                    f"{upstream}: row claims {claimed} unported and "
                    f"{os.path.basename(wl)} has no '### Portable - N' section, "
                    f"so this check can neither confirm nor contradict it")
            continue

        n_heading, annotation = heads[0]
        n_heading = int(n_heading)

        # A heading annotated "ported" says the expected remaining count is 0.
        # The `and claimed != 0` guard this replaced made the annotation inert
        # exactly when it agreed with the row: a correct 0 fell through to the
        # citation check below, which then reported the cases as uncited. The
        # selftest's known-NEGATIVE caught it on the first run, which is the
        # entire argument for writing the negative and not only the positives.
        if PORTED_NOTE.search(annotation):
            if claimed != 0:
                findings.append(
                    f"{upstream}: row claims {claimed} unported, but "
                    f"{os.path.basename(wl)}'s heading says: "
                    f"'### Portable - {n_heading}{annotation.rstrip()}'")
            continue

        # A later "Ported since ..." section contradicts it too.
        later = re.search(r"^###\s+Ported since[^\n]*$", text, re.M)
        if later:
            if claimed != 0:
                findings.append(
                    f"{upstream}: row claims {claimed} unported, but "
                    f"{os.path.basename(wl)} says: '{later.group(0).strip()}'")
            continue

        # Otherwise: how many of the named cases are cited by a test?
        section = text[text.index(f"### Portable"):]
        nxt = re.search(r"\n###\s", section[3:])
        if nxt:
            section = section[: nxt.start() + 3]
        cases = sorted(set(CASE.findall(section)))
        if not cases:
            unverified.append(
                f"{upstream}: '### Portable - {n_heading}' names no cases in "
                f"backticks, so there is nothing to reconcile against")
            continue
        uncited = [c for c in cases if c not in tests_blob]
        if len(uncited) != claimed:
            findings.append(
                f"{upstream}: row claims {claimed} unported; "
                f"{len(cases)} case(s) named, {len(uncited)} not cited by any "
                f"test — {', '.join(uncited) if uncited else '(all cited)'}")

    if checked == 0:
        die("matched 0 worklists to table rows; the naming convention changed "
            "and this check is measuring nothing")

    # Unverifiable rows are printed either way. They are not failures -- a
    # worklist is allowed to describe its portable cases in prose -- but they
    # are the rows where this check is silent, and a check that does not say
    # where it is silent is how a partial guard gets read as a full one.
    if unverified:
        print(f"{len(unverified)} row(s) this check cannot verify:\n")
        for u in unverified:
            print(f"  {u}")
        print()

    if findings:
        print(f"next-upstream.md's remaining-work table CONTRADICTS its own "
              f"evidence in {len(findings)} place(s):\n")
        for f in findings:
            print(f"  {f}")
        print("\nEach row should match the worklist it summarises. A row that was "
              "right when written and never revisited is how this table reached "
              "18 when the evidence said 2-4.")
        return 1

    print(f"next-upstream.md reconciles with {checked} worklist(s); "
          f"{len(unverified)} row(s) unverifiable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
