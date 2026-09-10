#!/usr/bin/env python3
"""Fail if a test PASSED without its assertions ever executing.

A test can pass because an assertion was never REACHED -- a guard that was not
entered, an early return, a helper that swallowed the failure. It reports green
and measures nothing, and no amount of reading the pass/fail column reveals it.
That is not hypothetical: ports#172 was a test whose assertion ran and could not
distinguish the two behaviours it named, and ports#173 was a harness action that
silently did nothing, which turned five recovery tests into no-crash controls
that passed. This checks the third member of that family, and it is the one that
is exactly measurable.

The measurement is coverage over the TEST FILES themselves, not over the code
under test. Run the suite under `coverage run`, then point this at the port.

WHAT IS AND IS NOT A FINDING, because the first version of this got it wrong.

Six of the seven tests it first flagged were healthy. Their unexecuted "checks"
were `pytest.fail(...)` calls on a FAILURE path -- the `else` of a `while/else`
that broke on success, or a guard on a bad status. Those correctly do not run
when the test passes; counting them describes a working test as a broken one.

So a missed check is only a finding when it sits on a path the test was expected
to take:

  EXPECTED    pytest.fail (a failure path by construction), or any check nested
              inside an if/try/except or a loop `else`
  SUSPICIOUS  an unconditional assert / wait_until / await_terminal that never
              executed in a test that did not skip

OUTCOMES ARE REQUIRED, and this was found by falsifying this file. An
earlier version routed any test with zero executed checks into a benign
"not measured" bucket, on the theory that those were setup errors. A planted
test that PASSED while asserting nothing -- the exact shape this exists to catch
-- landed in that bucket and the check exited 0. Coverage data alone cannot tell
"errored before asserting" from "passed without asserting"; only the run's
outcomes can. So a JUnit XML is required, and a test is judged only if it PASSED.

KNOWN FALSE POSITIVE, deliberately not suppressed. A conditional `pytest.skip()`
exits by raising, so an assertion AFTER it is unconditional in the AST and does
not run while the skip fires. `test_recovery.py`'s cleat#1111 pin is exactly
this. Suppressing it would need a rule that also hides real findings, so it is
reported and explained here instead -- the count to compare against is in
ASSERTIONS-BASELINE, and a rise above it is what matters.
"""
import ast
import json
import os
import pathlib
import subprocess
import sys

CHECKS = {"wait_until", "await_terminal"}
FAILURE_CALLS = {"fail"}
# Tests whose post-skip assertion is unconditional-by-AST; see the docstring.
BASELINE = {
    ("test_recovery.py",
     "test_a_worker_lost_mid_backoff_resumes_the_retry_rather_than_restarting_it"),
}


def executed_lines(port: pathlib.Path):
    """Executed line numbers per test file, from coverage's own JSON export.

    The interpreter path must be ABSOLUTE but NOT resolved, and the difference
    bit twice in five minutes.

    Absolute, because this runs with cwd=port: a relative
    `ports/dbos-transact-py/.venv/bin/python` is then looked up UNDER the port
    and does not exist, while `py.exists()` evaluated from the caller's cwd says
    it does. The two disagree silently.

    Not RESOLVED, because `.venv/bin/python` is a symlink chain ending at the
    system interpreter. `.resolve()` follows it out of the virtualenv to
    /opt/.../python3.14, which has no `coverage` installed -- a venv works by
    the path you invoke, not by the real binary behind it. Resolving turned
    "use the venv" into "use the system python" with no error, and the symptom
    was `No module named coverage` naming a package that is installed.
    """
    py = (port / ".venv" / "bin" / "python").absolute()
    if not py.exists():
        py = pathlib.Path(sys.executable).absolute()
    done = subprocess.run(
        [str(py), "-m", "coverage", "json", "-o", "-"],
        cwd=port, capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip():
        print("could not read coverage data. Run the suite under coverage first:\n"
              "  coverage run -m pytest tests/\n"
              f"coverage said: {done.stderr.strip()[-400:]}", file=sys.stderr)
        return None
    data = json.loads(done.stdout)
    return {pathlib.Path(f).name: set(d["executed_lines"])
            for f, d in data["files"].items()}


def checks_in(fn: ast.FunctionDef):
    """(line, kind, guarded) for every check in a test body."""
    found = []

    def walk(node, guarded):
        for child in ast.iter_child_nodes(node):
            g = guarded or isinstance(node, (ast.If, ast.Try, ast.ExceptHandler))
            if isinstance(node, (ast.While, ast.For)) and child in node.orelse:
                g = True
            if isinstance(child, ast.Assert):
                found.append((child.lineno, "assert", g))
            elif isinstance(child, ast.Call):
                name = getattr(child.func, "id", None) or getattr(child.func, "attr", "")
                if name in CHECKS:
                    found.append((child.lineno, name, g))
                elif name in FAILURE_CALLS:
                    found.append((child.lineno, "pytest.fail", True))
            walk(child, g)

    walk(fn, False)
    return found


def outcomes(xml_path: pathlib.Path):
    """testname -> "passed" | "failed" | "error" | "skipped", from JUnit XML."""
    import xml.etree.ElementTree as ET
    out = {}
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        name = case.get("name", "")
        kind = "passed"
        for child in case:
            tag = child.tag.lower()
            if tag in ("failure", "error", "skipped"):
                kind = {"failure": "failed"}.get(tag, tag)
                break
        out[name] = kind
    return out


def main():
    if len(sys.argv) != 3:
        print("usage: check-assertions-executed.py <port-dir> <junit-xml>",
              file=sys.stderr)
        return 2
    port = pathlib.Path(os.path.abspath(sys.argv[1]))
    xml = pathlib.Path(os.path.abspath(sys.argv[2]))
    if not (port / "tests").is_dir():
        print(f"no tests/ under {port}", file=sys.stderr)
        return 2
    if not xml.is_file():
        print(f"no JUnit XML at {xml}. Run:\n"
              f"  coverage run -m pytest --junitxml={xml} tests/", file=sys.stderr)
        return 2

    ex_by_file = executed_lines(port)
    if ex_by_file is None:
        return 2
    result = outcomes(xml)
    if not result:
        print(f"{xml} lists no test cases; refusing to report a clean sweep over "
              f"nothing.", file=sys.stderr)
        return 2

    suspicious, expected, clean, not_judged = [], 0, 0, []
    for f in sorted((port / "tests").glob("test_*.py")):
        ex = ex_by_file.get(f.name)
        for node in ast.parse(f.read_text()).body:
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                continue
            # Parametrized cases appear as name[param]; treat the test as passed
            # only if every one of its cases did.
            cases = [v for k, v in result.items()
                     if k == node.name or k.startswith(node.name + "[")]
            if not cases:
                not_judged.append(f"{f.name}::{node.name} (absent from the report)")
                continue
            if any(c != "passed" for c in cases):
                # skipped, failed or errored -- its assertions not running says
                # nothing about whether it can fail.
                continue
            if ex is None:
                not_judged.append(f"{f.name} (no coverage data)")
                continue
            found = checks_in(node)
            positives = [c for c in found if c[1] != "pytest.fail"]
            if not positives:
                # A test whose only mechanism is `if wrong: fail()` is legitimate;
                # its check not running is the success case.
                clean += 1
                continue
            missed = [c for c in positives if c[0] not in ex]
            if not missed:
                clean += 1
                continue
            for line, kind, guarded in missed:
                if guarded or (f.name, node.name) in BASELINE:
                    expected += 1
                else:
                    suspicious.append((f.name, node.name, line, kind))

    print(f"assertion-execution check: {clean} passing test(s) with every "
          f"unconditional check executed; {expected} unexecuted on conditional paths")
    for u in not_judged:
        print(f"  NOT JUDGED: {u}")

    if suspicious:
        print(f"\n{len(suspicious)} assertion(s) never executed in a test that PASSED.")
        print("Each is either a test that cannot fail, or an entry BASELINE needs "
              "with a reason:")
        for fn, name, line, kind in suspicious:
            print(f"  {fn}:{line}  {kind}  in {name}")
        return 1
    return 0


if __name__ == "__main__":
    # Exit codes carry meaning here and must not collide:
    #   0  every unconditional assertion in a passing test executed
    #   1  a FINDING -- an assertion that never ran
    #   2  this check could not run (bad args, no data, a bug in here)
    # An uncaught exception exits 1 by default, which would render a crash in
    # this file as a finding about the suite. That happened once already.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- deliberately broad
        import traceback
        traceback.print_exc()
        print(f"\ncheck-assertions-executed could not run: {exc!r}\n"
              "Exiting 2. This says nothing about the test suite.",
              file=sys.stderr)
        sys.exit(2)
