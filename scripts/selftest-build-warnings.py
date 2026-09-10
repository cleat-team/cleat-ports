#!/usr/bin/env python3
"""Self-test for the Python harness's build-warning filter.

Lives here rather than in ports/dbos-transact-py/tests/ for two reasons. A new
module there is a new row in the generated README inventory -- the single most
contended file in this repo, which three of tonight's pull requests collided on
-- and it would have to be accounted for in count-queue-cases.py's MAPPING. And
conftest.py cannot be imported without a 3.10+ interpreter: its
`list[str] | None` annotations are evaluated at def time, and on macOS's system
python 3.9 importing it raises `TypeError: unsupported operand type(s) for |`.
The port job pins 3.12 via actions/setup-python, but THIS step runs in the
`discover` job, which pins nothing and takes whatever the runner image ships.
A pure text filter should depend on neither pytest nor an unpinned interpreter
version, so it does not import conftest at all.

The interpreter is printed below so that assumption is visible rather than
inferred -- I asserted a version relationship here once already and had only
measured it on my own machine.

The Go ports test the same filter in tests/buildwarnings_test.go, where a test
module costs nothing. This exists so the PYTHON copy is covered too rather than
assumed to match: the two implementations share a design and not a line of code.

No database, no services, runs in milliseconds -- the same argument
scripts/selftest-fixture-service.py and scripts/selftest-report-path.sh make.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_warnings import build_warnings  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


# Verbatim stderr from scripts/build-workflow.sh on a workflow whose only
# parameter is a single string -- the W003 shape. Pasted rather than generated,
# because generating it needs the WASM toolchain and the thing under test is a
# text filter. Pasting REAL output is the point: a fixture written from memory
# would agree with my belief about the wording rather than with the toolchain,
# and would keep agreeing after the wording changed.
W003_STDERR = """\
  Analyzing package cleatports/w003pkg...
  Found 1 functions, 1 entry point(s), 0 in cleat closure.
  Durable leaves: (none)
  Verifying HostCalls threading... OK

  Warning: HandleW003Probe:6: HandleW003Probe is a workflow entry point whose only parameter is a single string, so "marker" receives the ENTIRE input JSON rather than the field of that name. Starting it with {"marker": "value"} binds marker to the literal text {"marker":"value"}. [W003]
    suggestion: If that is what you want -- an opaque payload the workflow parses itself -- nothing needs to change. If you meant to bind one field by name, add a second parameter or take a struct: func(h cleat.HostCalls, marker string, tag string). Struct parameters are unmarshalled from the input JSON and bind by field.

  Generating WASM imports (0 host functions used)... OK
  Generating host adapter... OK
  Generating WASM exports (1 entry point(s))... OK
  Auto-threading: no changes needed
  Build directory: /tmp/w003out
  Compiling WASM module (go/wasip1)...
  Wrote /tmp/w003out/handle_w003_probe.wasm (3.1 MB)
  Embedded metadata: handle_w003_probe.wasm v1 (ABI v1)

  Warning: host function "cleat_complete" imported from WASM env but not in computed closure; either the closure analysis missed a call path or the WASM binary includes unused imports
  Warning: host function "cleat_poll_work" imported from WASM env but not in computed closure; either the closure analysis missed a call path or the WASM binary includes unused imports
"""


def main():
    print(f"interpreter: {sys.version.split()[0]} ({sys.executable})")
    shown, suppressed = build_warnings(W003_STDERR)
    # NOT a canary for cleat#1125/#1126. W003_STDERR is a FROZEN capture, so this
    # count stays 2 however cleat changes -- this file cannot see the fix and will
    # not report that the filter has gone dead. Stated because the opposite was
    # assumed out loud.
    #
    # The general form, not specific to warnings: a guard cannot detect its own
    # obsolescence from a fixture that froze before the change. That applies to
    # every golden file and captured output here, so the obligation is to name
    # the live signal rather than trust the fixture to notice.
    #
    # The live signal is the suppressed count that the harness
    # prints on real builds; when cleat-version.env's CLEAT_PINNED_REF (currently
    # `develop`, unpinned) picks up the fix, that goes to 0 and the filter can go.
    check("the 2 unconditional warnings are suppressed", suppressed == 2,
          f"suppressed={suppressed}")
    check("exactly one real warning survives", len(shown) == 1, f"shown={len(shown)}")
    if len(shown) == 1:
        for want in ("W003", "HandleW003Probe", "ENTIRE input JSON"):
            check(f"the surviving warning still names {want!r}", want in shown[0],
                  "a reader could not tell which function or which mistake it is about")

    # Without this, a filter that suppressed nothing would still satisfy the
    # count above, and every build would log two lines that mean nothing -- the
    # noise this filter exists to remove.
    clean = (
        '  Wrote handle_x.wasm (4.6 MB)\n'
        '  Warning: host function "cleat_complete" imported from WASM env but not in '
        'computed closure; either the closure analysis missed a call path or the WASM '
        'binary includes unused imports\n'
        '  Warning: host function "cleat_poll_work" imported from WASM env but not in '
        'computed closure; either the closure analysis missed a call path or the WASM '
        'binary includes unused imports'
    )
    shown, suppressed = build_warnings(clean)
    check("a build with only unconditional warnings reports nothing",
          shown == [] and suppressed == 2, f"shown={shown} suppressed={suppressed}")

    shown, suppressed = build_warnings(
        "  Analyzing package cleatports/x...\n  Durable leaves: (none)\n  Wrote x.wasm")
    check("ordinary build chatter is not classified as a warning",
          shown == [] and suppressed == 0, f"shown={shown} suppressed={suppressed}")

    shown, suppressed = build_warnings(None)
    check("empty stderr is handled", shown == [] and suppressed == 0)

    print("\nFAILURES:", ", ".join(FAILS) if FAILS else "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
