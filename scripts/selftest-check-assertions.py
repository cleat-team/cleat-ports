#!/usr/bin/env python3
"""Prove check-assertions-executed.py still distinguishes its four cases.

Written because the check's FIRST version got this wrong in the direction that
matters: it routed a test which passed while asserting nothing -- the exact
shape it exists to catch -- into a benign bucket and exited 0. A check whose
own failure mode is "reports clean" needs a test that plants the defect and
demands a red.

The four shapes, and why each must land where it does:

  asserts normally           passes, assertion runs        -> clean
  passes without asserting   unconditional assert skipped  -> SUSPICIOUS, exit 1
  failure path not taken     only mechanism is fail()      -> clean, not a finding
  errors at setup            never reached its assertion   -> excluded, not a finding

The third and fourth are the ones that make this worth running: both look
identical to the second in coverage data alone, and calling either a finding
would make the check unusable noise.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

PROBE = '''
def test_asserts_normally():
    x = 2
    assert x == 2


def test_passes_without_ever_asserting():
    if False:
        assert 1 == 2
    return
    assert 1 == 2


def test_failure_path_not_taken():
    import pytest
    ok = True
    while True:
        if ok:
            break
    else:
        pytest.fail("never")


def test_errors_at_setup(a_fixture_that_does_not_exist):
    assert True
'''


def interpreter(here: pathlib.Path) -> str:
    """An interpreter that HAS pytest and coverage.

    Not sys.executable. This is invoked as `python3 scripts/selftest-...` and
    the system python3 has neither, so the probe suite fails to run and the
    selftest reports "cannot conclude anything" -- which is the correct thing
    to say and is not what a reader skimming a green log expects to matter.
    Prefer the port venv the check itself uses.
    """
    for cand in sorted((here.parent / "ports").glob("*/.venv/bin/python")):
        # .absolute(), never .resolve(): resolving this symlink chain lands on
        # the system interpreter and loses the virtualenv. Same trap as the
        # check itself hit.
        return str(cand.absolute())
    return sys.executable


def main():
    here = pathlib.Path(__file__).resolve().parent
    check = here / "check-assertions-executed.py"
    py = interpreter(here)
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        (tmp / "tests").mkdir()
        (tmp / "tests" / "test_probe.py").write_text(PROBE)
        xml = tmp / "j.xml"
        run = subprocess.run(
            [py, "-m", "coverage", "run", "--source=tests", "-m", "pytest",
             "-q", f"--junitxml={xml}", "tests/"],
            cwd=tmp, capture_output=True, text=True)
        if "3 passed" not in run.stdout or "1 error" not in run.stdout:
            print("the probe suite did not behave as designed; the selftest "
                  f"cannot conclude anything:\n{run.stdout[-800:]}", file=sys.stderr)
            return 2

        done = subprocess.run([py, str(check), str(tmp), str(xml)],
                              cwd=tmp, capture_output=True, text=True)
        out = done.stdout

        problems = []
        if done.returncode != 1:
            problems.append(f"expected exit 1, got {done.returncode}")
        if "test_passes_without_ever_asserting" not in out:
            problems.append("did NOT flag the test that passed without asserting "
                            "-- this is the failure the check exists to prevent")

        # EXACTLY one finding, not "at least one". Counting was added after a
        # mutation that made the check report every guarded assertion as a
        # finding sailed through a presence-only assertion: the probe's guarded
        # `if False: assert` belongs to the SAME test, so an over-reporting
        # check still printed the expected name and looked correct. A checker
        # that cannot fail for over-reporting only guards one direction.
        n = sum(1 for line in out.splitlines()
                if line.strip().startswith("test_probe.py:"))
        if n != 1:
            problems.append(f"expected exactly 1 finding, got {n} -- "
                            f"over-reporting is as broken as under-reporting")
        for benign in ("test_failure_path_not_taken", "test_errors_at_setup"):
            # they may appear in NOT JUDGED lines; they must not appear as findings
            findings = out.split("never executed in a test that PASSED")[-1]
            if benign in findings:
                problems.append(f"flagged {benign}, which is not a defect")

        if problems:
            print("selftest FAILED:")
            for p in problems:
                print(f"  - {p}")
            print(f"\n--- check output ---\n{out}\n{done.stderr}")
            return 1
        print("selftest passed: flags the vacuous test, and only that one")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
