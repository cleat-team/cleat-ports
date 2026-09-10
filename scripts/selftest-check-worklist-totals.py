#!/usr/bin/env python3
"""Known-positives and known-negatives for check-worklist-totals.py.

A reconciliation guard has two ways to be worthless and only one of them is
loud. It can miss a real discrepancy -- caught by the positives below. Or its
parser can stop matching anything, at which point it reports success over an
empty set forever; that is the failure this repository keeps meeting, so the
last two cases assert the checker EXITS 2 rather than 0 when it can see nothing.

Run: python3 scripts/selftest-check-worklist-totals.py
"""

import os
import subprocess
import sys
import tempfile

CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "check-worklist-totals.py")

TABLE = """# Scoping a second upstream

| upstream file | cases | portable, unported |
|---|---:|---:|
| `test_alpha.py` | 10 | {alpha} |
| `test_beta.py` | 20 | {beta} |
"""


def build(tmp, alpha_claim, beta_claim, alpha_head, beta_head,
          alpha_cases="`test_one`", cited=("test_one",)):
    os.makedirs(os.path.join(tmp, "docs"), exist_ok=True)
    wl = os.path.join(tmp, "ports", "dbos-transact-py", "worklists")
    ts = os.path.join(tmp, "ports", "dbos-transact-py", "tests")
    os.makedirs(wl, exist_ok=True)
    os.makedirs(ts, exist_ok=True)
    with open(os.path.join(tmp, "docs", "next-upstream.md"), "w") as f:
        f.write(TABLE.format(alpha=alpha_claim, beta=beta_claim))
    with open(os.path.join(wl, "test-alpha.md"), "w") as f:
        f.write(f"## alpha\n\n{alpha_head}\n\n| case |\n|---|\n| {alpha_cases} |\n")
    with open(os.path.join(wl, "test-beta.md"), "w") as f:
        f.write(f"## beta\n\n{beta_head}\n\n| case |\n|---|\n| `test_two` |\n")
    with open(os.path.join(ts, "test_ported.py"), "w") as f:
        f.write("\n".join(f'def {c}():\n    """upstream {c}."""\n' for c in cited))
    return tmp


def run(tmp):
    env = dict(os.environ, CLEAT_PORTS_ROOT=tmp)
    p = subprocess.run([sys.executable, CHECK], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def case(name, want_code, want_text, **kw):
    with tempfile.TemporaryDirectory() as tmp:
        build(tmp, **kw)
        code, out = run(tmp)
    ok = code == want_code and (want_text in out)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  (exit {code}, wanted {want_code})")
    if not ok:
        print(f"        wanted text: {want_text!r}")
        print("        got:\n" + "".join("          " + l + "\n" for l in out.splitlines()))
    return ok


def main():
    results = []
    print("known-NEGATIVE -- a reconciled table must pass:")
    results.append(case(
        "both rows 0 against ported headings", 0, "reconciles with 2 worklist",
        alpha_claim="0", beta_claim="0",
        alpha_head="### Portable — 1 · **ported 2026-01-01**",
        beta_head="### Portable — 1 · **ported 2026-01-01**"))

    print("known-POSITIVE -- each must be caught:")
    results.append(case(
        "row claims work against a 'ported' heading", 1, "heading says",
        alpha_claim="1", beta_claim="0",
        alpha_head="### Portable — 1 · **ported 2026-01-01**",
        beta_head="### Portable — 1 · **ported 2026-01-01**"))
    results.append(case(
        "row claims work but every case is cited by a test", 1, "all cited",
        alpha_claim="1", beta_claim="0",
        alpha_head="### Portable — 1",
        beta_head="### Portable — 1 · **ported 2026-01-01**"))
    results.append(case(
        "a genuinely unported case is NOT reported as reconciled", 1, "not cited by any",
        alpha_claim="0", beta_claim="0",
        alpha_head="### Portable — 1",
        beta_head="### Portable — 1 · **ported 2026-01-01**",
        alpha_cases="`test_never_ported`", cited=("test_one",)))

    print("REPORTED BUT NOT FAILED -- a row with no evidence either way:")
    # This case was a known-POSITIVE until the checker learned to separate
    # "contradicts the evidence" from "has no evidence". A worklist is allowed
    # to describe its portable cases in prose, so this must not fail the build
    # -- but it must still be PRINTED, because a check that is silent about
    # where it is silent gets read as covering more than it does. The assertion
    # is therefore on the text, not only on the exit code.
    results.append(case(
        "row with no Portable heading is reported, and does not fail", 0,
        "can neither confirm nor contradict",
        alpha_claim="1", beta_claim="0",
        alpha_head="### Something Else — 1",
        beta_head="### Portable — 1 · **ported 2026-01-01**"))

    print("VACUITY -- the checker must refuse to pass over an empty set:")
    with tempfile.TemporaryDirectory() as tmp:
        build(tmp, "0", "0", "### Portable — 1 · **ported**", "### Portable — 1 · **ported**")
        # Break the table so no row parses.
        with open(os.path.join(tmp, "docs", "next-upstream.md"), "w") as f:
            f.write("# Scoping a second upstream\n\nno table here at all\n")
        code, out = run(tmp)
        ok = code == 2 and "parsed 0 rows" in out
        print(f"  {'PASS' if ok else 'FAIL'}  unparseable table exits 2, not 0 (exit {code})")
        if not ok:
            print("        got:\n" + "".join("          " + l + "\n" for l in out.splitlines()))
        results.append(ok)

    with tempfile.TemporaryDirectory() as tmp:
        build(tmp, "0", "0", "### Portable — 1 · **ported**", "### Portable — 1 · **ported**")
        # Rename the worklists so nothing matches a row.
        wl = os.path.join(tmp, "ports", "dbos-transact-py", "worklists")
        for n in os.listdir(wl):
            os.rename(os.path.join(wl, n), os.path.join(wl, "renamed-" + n))
        code, out = run(tmp)
        # Exit 2, not 1: if NOT ONE row matches a worklist the naming convention
        # has moved and the check is measuring nothing, which is a different
        # thing from finding a discrepancy. This expectation was wrong on the
        # first run -- it wanted 1 -- and the checker was right.
        ok = code == 2 and "matched 0 worklists" in out
        print(f"  {'PASS' if ok else 'FAIL'}  no row matching any worklist exits 2, not 0 or 1 (exit {code})")
        if not ok:
            print("        got:\n" + "".join("          " + l + "\n" for l in out.splitlines()))
        results.append(ok)

    print()
    if all(results):
        print(f"all {len(results)} selftest cases pass")
        return 0
    print(f"{sum(1 for r in results if not r)} of {len(results)} selftest cases FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
