"""The build-warning filter, shared by the Python harness and its self-test.

In scripts/ rather than in ports/dbos-transact-py/tests/ for two reasons, both
practical. A module added to tests/ has to be accounted for in
count-queue-cases.py's MAPPING or --check fails, and it lands in the generated
README inventory -- the single most contended file in this repo. And the
self-test runs in CI's `discover` job, which pins no Python version; only the
port job sets up 3.12. conftest.py needs 3.10+ to import at all, because its
`list[str] | None` annotations are evaluated at def time -- on macOS's system
python 3.9 the import raises TypeError.

Importing conftest for one pure function would therefore couple a text filter to
pytest and to a Python version it has no reason to care about.
"""

# Emitted by every WASM build of every workflow, including one that makes no
# host calls at all, so they say nothing about the package being built. cleat's
# generator emits both imports unconditionally -- wasm/generator.go, "Always
# include cleat_complete -- the export wrapper calls it" -- while wasm/scan.go
# compares the binary's imports against the WORKFLOW's computed closure, which
# they are never in by construction. Filed as cleat#1125.
#
# Filtered rather than tolerated because the point of surfacing warnings is that
# someone reads them, and a channel that cries wolf twice on every build is one
# nobody reads. Not hypothetical: ports/durabletask-go/README.md records a W003
# warning that correctly predicted a failure, went unnoticed, and was nearly
# filed as a cleat defect instead.
UNCONDITIONAL = (
    'host function "cleat_complete" imported from WASM env but not in computed closure',
    'host function "cleat_poll_work" imported from WASM env but not in computed closure',
)


def build_warnings(stderr):
    """Split a build's stderr into warnings worth showing and a suppressed count.

    Pure and separate from any reporting, so it can be tested against real
    captured toolchain output rather than a hand-written imitation of it. The
    filter's whole job is to match what the toolchain actually prints; a fixture
    written from memory would agree with my belief about the wording rather than
    with the toolchain, and would go on agreeing after the wording changed.
    """
    shown, suppressed = [], 0
    for line in (stderr or "").splitlines():
        line = line.strip()
        if "Warning:" not in line:
            continue
        if any(u in line for u in UNCONDITIONAL):
            suppressed += 1
            continue
        shown.append(line)
    return shown, suppressed


def format_build_warnings(pkg_name, stderr):
    """The message to show, or None when there is nothing worth showing."""
    shown, suppressed = build_warnings(stderr)
    if not shown:
        return None
    return (
        f"building {pkg_name} produced {len(shown)} toolchain warning(s); "
        f"{suppressed} unconditional ones suppressed (cleat#1125).\n"
        "These are PREDICTIONS: a warning here usually surfaces later as a wrong "
        "RESULT rather than as a build error.\n  " + "\n  ".join(shown)
    )
