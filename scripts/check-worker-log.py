#!/usr/bin/env python3
"""Report background errors the worker logged, and fail on unexplained ones.

WHY THIS EXISTS. A port suite asserts on workflow outcomes over HTTP. The
worker's own background loops -- schedulers, reapers, pollers -- fail without
failing anything, so a suite can be green while a subsystem errors on every
tick. That is not hypothetical: one nightly's mssql leg carried 74 SQL errors
from seven plugins, in a passing run, and nobody had seen them because

  - no test asserts on them,
  - CI's log upload was silently discarding the file (fixed in ports#162), and
  - the plugin's own success line does not distinguish "nothing was due" from
    "the query failed" -- `scheduler: work cycle completed` is logged on the
    same cycles whose query errored.

So this reads the log the run just produced and says what is in it.

KNOWN is an allowlist, and it is deliberately specific rather than a pattern
like "mssql:". Every entry names an upstream issue and the exact text. A new
failure mode -- a different construct, a different plugin -- is NOT matched by
an entry written for an old one, which is the whole point: the allowlist must
not grow to cover things nobody has looked at.

The counts are REPORTED even when they match. A silent allowlist is a filter
that has stopped meaning anything; when cleat#1133 is fixed these go to zero and
that is the signal to delete the entries.
"""
import os
import pathlib
import re
import sys

# (substring, upstream issue). Matched against the whole log line.
KNOWN = [
    ("mssql: Invalid column name 'true'.", "cleat#1133"),
    ("mssql: Invalid column name 'id'.", "cleat#1133"),
    ("mssql: Incorrect syntax near 'LIMIT'.", "cleat#1133"),
    ("mssql: Invalid usage of the option NEXT in the FETCH statement.", "cleat#1133"),
    # Text transcribed from the log itself, not from a truncated quote of it.
    # Both this entry and the pq one below were initially wrong because they
    # were copied from output cut at 70 columns -- this one assumed a full stop
    # where the message continues ", near 'AND'.", and the pq one omitted the
    # backslash-escaped quotes. The check refused to match them, which is what
    # a specific allowlist is for.
    ("mssql: An expression of non-boolean type specified in a context where a condition is expected",
     "cleat#1133"),
    ("mssql: 'now' is not a recognized built-in function name.", "cleat#1133"),
    (r'pq: syntax error at or near \"LIMIT\"', "cleat#1133"),
    ("Error 1064 (42000)", "cleat#1133"),
    # email-notify has no sendgrid key in this harness and fails init, once,
    # then stays inert. Not a defect -- the plugin is simply unconfigured, and
    # its single line is what distinguishes "unconfigured" from "configured and
    # broken" for everything above it.
    ("sendgrid_api_key is required in plugin config", "unconfigured in this harness"),
]

# Workflow-level failures are NOT this file's business, and the first CI run is
# why. It listed the workflow names that samples-go and dbos-transact-py fail on
# purpose, and durabletask-go promptly failed on `handle_failing_child` -- a
# deliberate failure from the Test_SingleSubOrchestrator_Failed port, absent
# from a list written before that port existed.
#
# Hand-maintaining that list is a standing tax on every future port that asserts
# a failure, and it would fail exactly this way each time. The scope is wrong,
# not the list: an `execution error` means a WORKFLOW failed, and a workflow
# failing unexpectedly already fails the test that asserts on it. There is
# nothing here for this check to add.
#
# What no test can see is the other kind -- background loops that error without
# failing anything. That is the whole reason this file exists, so that is all it
# looks at.
EXECUTION = re.compile(r'"msg":"execution error"')


def error_lines(text):
    """Lines the worker logged at ERROR, in either of its two formats.

    The worker writes BOTH structured JSON lines and plain-text
    `2026/09/10 01:14:42 ERROR name: msg plugin=name` lines. A search of one
    format finds nothing in the other, which is how a survey of these once
    concluded the plugins logged no lifecycle at all.
    """
    out = []
    for line in text.splitlines():
        if '"level":"ERROR"' in line or re.search(r"\bERROR\b", line):
            out.append(line.strip())
    return out


def main():
    root = pathlib.Path(os.environ.get("CLEAT_PORTS_RESULTS_ROOT")
                        or (pathlib.Path(__file__).resolve().parent.parent / ".port-results"))
    logs = sorted(root.glob("**/worker*.log"))
    if not logs:
        # Distinguish the two reasons there is no log, because one of them is a
        # broken check and the other is a run that never got far enough. This
        # step is `if: always()`, so it also runs when the port aborted during
        # setup -- failing then would report a second, misleading failure.
        #
        # No results directory at all -> the harness never started. Say so and
        # pass; the real failure is upstream in the job.
        # A results directory with no worker log in it -> the log moved, or the
        # worker never wrote one, and this check has silently stopped checking.
        # That is the failure mode this whole file exists to prevent, so it is
        # an error rather than a quiet zero.
        if not root.exists():
            print(f"NOT CHECKED: no {root} -- the harness did not start; "
                  f"see the failure above this step", file=sys.stderr)
            return 0
        print(f"NOT CHECKED, AND THAT IS AN ERROR: {root} exists but contains no "
              f"worker*.log. Either the log path moved or the worker wrote none. "
              f"A check that reads nothing reports success forever.", file=sys.stderr)
        return 1

    unexplained = []
    known_hits = {}
    scanned = 0
    for log in logs:
        text = log.read_text(encoding="utf-8", errors="replace")
        for line in error_lines(text):
            scanned += 1
            if EXECUTION.search(line):
                continue
            for needle, issue in KNOWN:
                if needle in line:
                    known_hits[issue] = known_hits.get(issue, 0) + 1
                    break
            else:
                unexplained.append((log.name, line[:200]))

    print(f"worker log check: {len(logs)} file(s), {scanned} ERROR line(s)")
    for issue, n in sorted(known_hits.items()):
        print(f"  {n:4d}  known: {issue}")
    if not known_hits:
        print("  no known-issue lines -- if cleat#1133 is fixed, delete its KNOWN entries")

    if unexplained:
        print(f"\n{len(unexplained)} UNEXPLAINED error line(s). Each is either a new defect "
              f"or an entry this file needs, with an issue number:")
        for name, line in unexplained[:20]:
            print(f"  {name}: {line}")
        if len(unexplained) > 20:
            print(f"  ... and {len(unexplained) - 20} more")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
