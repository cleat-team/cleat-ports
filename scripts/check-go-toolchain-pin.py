#!/usr/bin/env python3
"""The Go toolchain pin in CI is >= the floor cleat's go.work declares.

Nothing in cleat-ports is written in Go. The pin exists because
`make install-cleat` BUILDS cleat from source at CLEAT_PINNED_REF, and
`actions/setup-go` sets GOTOOLCHAIN=local, so a toolchain below cleat's
workspace floor cannot upgrade itself to satisfy it.

WHY A CHECK AND NOT JUST A CORRECT NUMBER. CLEAT_PINNED_REF is `develop`, a
MOVING ref. The pin is therefore not merely liable to rot, it is guaranteed to
-- on cleat's next floor move, in the same way, with the same symptom. That
happened on 2026-09-16: cleat#1714 took go.work to `go 1.26.0`, the pins said
1.25, and 4 of 4 port suites died (cleat-ports#251).

AND THE FAILURE NAMED THE WRONG THING. It surfaced three steps later as

    make: *** [Makefile:85: install-cleat] Error 1

so the job reporting a version mismatch was a build target. cleat's own
scripts/check-go-work-floor.sh header makes this argument about the mirror-image
case: "the refusal surfaces as a failure of whatever job happened to run go
build first". One sentence naming both files is the whole point.

WHY NOT `go-version-file`. It is the obvious answer and it cannot work here:
setup-go runs BEFORE install-cleat, and install-cleat is what puts cleat's
go.work on disk. So the floor has to be read over the network, from the ref the
build will use, before the toolchain is chosen.

EXIT STATUS, three-valued on purpose:

    0   every pin is at or above the floor
    1   a pin is below the floor
    2   the check could not establish what it was measuring

2 is separate from 1 because "no pins found" and "could not read the floor"
agree with every workflow file, correct or not. A check that measures nothing
must not be able to report the same thing as a check that measured and passed
-- which is the shape scripts/selftest-check-worklist-totals.py exists to guard
against in the job right next to this one.
"""

import argparse
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/nightly.yml")
ENV_FILE = "cleat-version.env"

# `go-version: <value>` in any of the quoting styles the tree uses, including the
# flow-mapping form `with: { go-version: "1.26" }` that both call sites use.
#
# The value is captured LOOSELY and classified afterwards, deliberately. An
# earlier version matched `(\d+(?:\.\d+)*)` and so did not match `stable`,
# `oldstable` or `1.26.x` -- all legal setup-go values. A file carrying one of
# those was then neither a failure nor a pin: it left the denominator in
# silence, and a run with one such file reported OK over half its subject
# (raised by a peer session against this script, the same defect as
# cleat#1730). A value this check cannot compare is now exit 2, not a pass.
PIN_RE = re.compile(r"""go-version:\s*['"]?([A-Za-z0-9_.-]+)['"]?""")
NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)*$")

# Every file that sets up Go must yield a comparable pin. Counting setup-go
# steps rather than assuming one pin per file, so that a file which stops using
# Go does not force a failure and a file which gains a second setup-go step is
# not checked once.
SETUP_GO_RE = re.compile(r"uses:\s*actions/setup-go@")
GO_DIRECTIVE_RE = re.compile(r"^go\s+(\d+(?:\.\d+)*)\s*$", re.M)


def version_tuple(v):
    return tuple(int(p) for p in v.split("."))


def compare(pin, floor):
    """Is `pin` at or above `floor`?

    Compared on the fields the PIN states. `go-version: "1.26"` selects the
    newest 1.26.x, so it satisfies a floor of 1.26.0 and must not be read as
    1.26 < 1.26.0. Truncating the floor to the pin's precision says exactly
    that, and still fails 1.25 against 1.26.0.
    """
    p = version_tuple(pin)
    f = version_tuple(floor)[: len(p)]
    return p >= f


def read_env(root):
    path = os.path.join(root, ENV_FILE)
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError as exc:
        return None, "cannot read %s: %s" % (ENV_FILE, exc)
    for key in ("CLEAT_PINNED_REF", "CLEAT_REPO"):
        if not out.get(key):
            return None, "%s does not set %s" % (ENV_FILE, key)
    return out, None


def fetch_floor(repo, ref, fetch):
    """The `go` directive from cleat's go.work at `ref`."""
    slug = repo.split("/", 1)[1] if "/" in repo else repo
    url = "https://raw.githubusercontent.com/%s/%s/go.work" % (slug, ref)
    try:
        body = fetch(url)
    except Exception as exc:  # network, 404, anything
        return None, "cannot read go.work at %s from %s: %s" % (ref, url, exc)
    m = GO_DIRECTIVE_RE.search(body)
    if not m:
        return None, (
            "go.work at %s has no `go` directive. That file is %d bytes and "
            "parsed to nothing, which is not the same as a workspace with no "
            "floor." % (ref, len(body))
        )
    return m.group(1), None


def http_get(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def find_pins(root, workflows):
    """([(path, lineno, version)], None) or (None, why-this-scan-cannot-verdict).

    Refuses on a per-FILE basis, not on the total. A total-only guard catches
    losing every pin and not losing one, and losing one is the likelier edit.
    """
    pins, problems = [], []
    for rel in workflows:
        path = os.path.join(root, rel)
        here, setups, uncomparable = [], 0, []
        try:
            with open(path) as fh:
                for n, line in enumerate(fh, 1):
                    if SETUP_GO_RE.search(line):
                        setups += 1
                    m = PIN_RE.search(line)
                    if not m:
                        continue
                    if NUMERIC_RE.match(m.group(1)):
                        here.append((rel, n, m.group(1)))
                    else:
                        uncomparable.append((n, m.group(1)))
        except OSError as exc:
            return None, "cannot read %s: %s" % (rel, exc)
        for n, val in uncomparable:
            problems.append(
                "%s:%d pins go-version %r, which this check cannot compare to a "
                "floor -- it does not know what version that resolves to at run "
                "time. A value it cannot verdict on must not read as a pass."
                % (rel, n, val))
        if setups and not here:
            problems.append(
                "%s sets up Go %d time(s) and yields no comparable pin, so it "
                "contributed nothing to this run. A file that leaves the "
                "denominator in silence is the failure this exit code exists "
                "for." % (rel, setups))
        pins.extend(here)
    if problems:
        return None, "\n".join(problems)
    return pins, None


def check(root, workflows=WORKFLOWS, fetch=http_get, env=None, floor=None):
    out = []
    if env is None:
        env, err = read_env(root)
        if err:
            return 2, ["SCAN FAILED: " + err]
    ref, repo = env["CLEAT_PINNED_REF"], env["CLEAT_REPO"]

    if floor is None:
        floor, err = fetch_floor(repo, ref, fetch)
        if err:
            return 2, ["SCAN FAILED: " + err]

    pins, err = find_pins(root, workflows)
    if err:
        return 2, ["SCAN FAILED: " + err]
    if not pins:
        return 2, [
            "SCAN FAILED: no `go-version` pin found in %s. Zero pins agrees "
            "with every floor, so this is a failure of the scan rather than a "
            "clean tree -- fix the pattern, do not delete the check."
            % ", ".join(workflows)
        ]

    out.append("cleat %s go.work floor: go %s" % (ref, floor))
    out.append("pins checked: %d, across %d file(s); every file that sets up Go "
               "yielded one" % (len(pins), len(workflows)))

    bad = [(p, n, v) for p, n, v in pins if not compare(v, floor)]
    if bad:
        for path, n, v in bad:
            out.append("")
            out.append(
                "%s:%d pins go-version %s, below the go %s that cleat's go.work "
                "declares at %s." % (path, n, v, floor, ref)
            )
        out.append("")
        out.append(
            "`make install-cleat` builds cleat from source at that ref and "
            "setup-go sets GOTOOLCHAIN=local, so the build cannot upgrade "
            "itself to satisfy the floor. Raise the pin to %s." % floor
        )
        return 1, out

    out.append("OK: every pin is at or above the floor.")
    return 0, out


# ---------------------------------------------------------------------------
# Self-test: a KNOWN-POSITIVE per outcome, run against synthetic inputs.
#
# Not "the tree still passes". A check whose only evidence is today's tree is
# indistinguishable from a check that always returns 0 -- which is exactly what
# the pins' silent rot looked like for the five hours before anyone noticed.
# ---------------------------------------------------------------------------

ENV_OK = {"CLEAT_PINNED_REF": "develop", "CLEAT_REPO": "github.com/cleat-team/cleat"}

SETUP = "steps:\n  - uses: actions/setup-go@v6\n    %s\n"

CASES = [
    # name,                        whole workflow file,                  floor,   rc, substring
    ("pin equals floor",           SETUP % 'with: { go-version: "1.26" }', "1.26.0", 0, "every pin is at or above"),
    ("pin above floor",            SETUP % 'with: { go-version: "1.27" }', "1.26.0", 0, "every pin is at or above"),
    ("pin below floor",            SETUP % 'with: { go-version: "1.25" }', "1.26.0", 1, "below the go 1.26.0"),
    ("the real cleat-ports#251",   SETUP % 'with: { go-version: "1.25" }', "1.26.0", 1, "GOTOOLCHAIN=local"),
    ("major below floor",          SETUP % 'with: { go-version: "1.9" }',  "1.26.0", 1, "below the go 1.26.0"),
    ("unquoted pin",               SETUP % "go-version: 1.25",             "1.26.0", 1, "below the go 1.26.0"),
    ("patch pin satisfies",        SETUP % 'go-version: "1.26.1"',         "1.26.0", 0, "every pin is at or above"),
    ("patch pin below",            SETUP % 'go-version: "1.26.0"',         "1.26.1", 1, "below the go 1.26.1"),

    # A file that sets up Go and yields nothing this check can compare. Each of
    # these is a LEGAL setup-go value, and under the first version of this
    # script each one silently left the denominator: the run reported OK over
    # the files that did have a numeric pin. Raised by a peer session, measured
    # end-to-end -- ci=1.26 with nightly=stable was exit 0, "pins checked: 1".
    ("`stable` is not a pin",      SETUP % "with: { go-version: stable }",    "1.26.0", 2, "cannot compare"),
    ("`oldstable` is not a pin",   SETUP % "with: { go-version: oldstable }", "1.26.0", 2, "cannot compare"),
    ("`1.26.x` is not a pin",      SETUP % 'with: { go-version: "1.26.x" }',  "1.26.0", 2, "cannot compare"),
    ("setup-go with no pin",       "steps:\n  - uses: actions/setup-go@v6\n", "1.26.0", 2, "yields no comparable pin"),

    # And the total-zero guard, which is a DIFFERENT failure: no setup-go at
    # all. Kept separate because the per-file guard above cannot fire here, and
    # a check that lost its pattern entirely must still refuse.
    ("no Go anywhere",             "steps:\n  - run: echo hi\n",             "1.26.0", 2, "Zero pins agrees"),
]


def self_test():
    import tempfile

    failures = []
    for name, body, floor, want_rc, want_sub in CASES:
        with tempfile.TemporaryDirectory() as td:
            rel = os.path.join(".github", "workflows", "ci.yml")
            os.makedirs(os.path.join(td, ".github", "workflows"))
            with open(os.path.join(td, rel), "w") as fh:
                fh.write(body)
            rc, lines = check(td, workflows=(rel,), env=dict(ENV_OK), floor=floor)
        body = "\n".join(lines)
        if rc != want_rc or want_sub not in body:
            failures.append("  %-24s rc=%d (want %d) body=%r" % (name, rc, want_rc, body))

    # The floor side, which the cases above hold fixed. A fetch that fails, and
    # a go.work with no directive, must both be 2 rather than 0.
    def boom(url):
        raise urllib.error.URLError("no route to host")

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, ".github", "workflows"))
        with open(os.path.join(td, ".github", "workflows", "ci.yml"), "w") as fh:
            fh.write('with: { go-version: "1.26" }\n')
        rel = (os.path.join(".github", "workflows", "ci.yml"),)
        rc, lines = check(td, workflows=rel, env=dict(ENV_OK), fetch=boom)
        if rc != 2 or "cannot read go.work" not in "\n".join(lines):
            failures.append("  %-24s rc=%d (want 2)" % ("unreachable go.work", rc))
        rc, lines = check(td, workflows=rel, env=dict(ENV_OK), fetch=lambda u: "// a comment only\n")
        if rc != 2 or "no `go` directive" not in "\n".join(lines):
            failures.append("  %-24s rc=%d (want 2)" % ("go.work with no directive", rc))

    # TWO FILES, because the defect this guards against is invisible with one:
    # a run whose other file is fine reports OK and prints a smaller count.
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, ".github", "workflows"))
        rels = []
        for name, val in (("ci.yml", '"1.26"'), ("nightly.yml", "stable")):
            rel = os.path.join(".github", "workflows", name)
            rels.append(rel)
            with open(os.path.join(td, rel), "w") as fh:
                fh.write(SETUP % ("with: { go-version: %s }" % val))
        rc, lines = check(td, workflows=tuple(rels), env=dict(ENV_OK), floor="1.26.0")
        body = "\n".join(lines)
        if rc != 2 or "nightly.yml" not in body:
            failures.append("  %-26s rc=%d (want 2, naming nightly.yml)" % ("one good file, one not", rc))

    if failures:
        print("SELF-TEST FAILED:")
        print("\n".join(failures))
        return 1
    print("OK: self-test passed, all %d cases classified correctly." % (len(CASES) + 3))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true",
                    help="run the known-positives and exit; touches no network")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    rc, lines = check(ROOT)
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
