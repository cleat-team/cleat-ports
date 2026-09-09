#!/usr/bin/env python3
"""Count the cases pytest actually collects from an upstream test file.

Why this exists: the obvious counts are both wrong.

  ast.walk() for every `test_*` FunctionDef      -> 103 for test_queue.py
  pytest actually collects                       ->  77

The 26-case gap is inner helper functions defined INSIDE test bodies. DBOS
tests declare their workflows and steps locally and name them `test_workflow`,
`test_step`, `test_child_wf`, `test_transaction` -- four distinct `test_step`
and three `test_workflow` across the file. They are local variables, never
collected. Counting them inflates the denominator and makes the port's
coverage look worse than it is.

pytest collects a `test_*` function only at module scope, or as a method of a
`Test*`-prefixed class. This script counts exactly that.

Usage:
  PIN=833794f7a1138bacf75ff6d88647a33eb5e35e52
  curl -sSL https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/$PIN/tests/test_queue.py -o /tmp/u.py
  python3 count-queue-cases.py /tmp/u.py [port_test_file ...]
"""
import ast, re, sys

# Controls cleat has no counterpart for. See ISSUES.md "no work queues".
#
# Both separators, deliberately. Upstream passes these options two ways: as
# keyword arguments (`Queue(name, worker_concurrency=2)`) and as dict literals
# in a parametrize table (`({"partition_concurrency": 0}, "at least 1")`).
# Matching only `=` missed the second form entirely and called
# test_partition_limit_validation portable -- twelve parametrized cases, every
# one of them constructing a Queue with a control cleat does not have, sitting
# in the work-list as 28% of it. A dict key is the same control as a kwarg; the
# syntax it is written in is not a property of cleat.
# `\w*partition\w*` rather than `partition_\w+`: upstream spells the same
# concept `partition_concurrency`, `partition_limiter` and
# `queue_partition_key`, and the last is a PREFIXED identifier. The
# original pattern caught it only as a substring of `queue_partition_key=`,
# which is the right verdict reached by an accident that a token-boundary
# fix would silently undo -- and did, on first attempt.
_CONTROLS = r'worker_concurrency|global_concurrency|limiter|\w*partition\w*|concurrency'
BLOCK = re.compile(r'(?<![_\w])["\']?(?:' + _CONTROLS + r')["\']?\s*[:=]'
                   r'|Queue\(\s*"[^"]*"\s*,\s*\d+')
# Controls cleat does have.
HAVE  = re.compile(r'priority|deduplication_id|dedup|app_version')

# Queue SEMANTICS, as distinct from queue CONTROLS.
#
# BLOCK catches a case that needs a knob cleat lacks -- a concurrency cap, a
# limiter, a partition. It does not catch a case that needs the QUEUE ITSELF to
# behave a particular way: a workflow sitting in ENQUEUED until a queue is
# registered, a DELAYED state, `delay_seconds`, the queue CRUD APIs. Those need
# no control at all and cleat still cannot express them, because it has no
# queues (ISSUES.md 20).
#
# Measured 2026-09-09 on test_queue.py: 11 of the 30 cases BLOCK calls portable
# are in this class, so the work-list overstated by 37% in the flattering
# direction. Two of them were picked off that list and abandoned on reading --
# test_enqueue_on_nonexistent_queue needs registration TIMING, and
# test_enqueue_with_options_unknown_workflow needs `delay_seconds` and a DELAYED
# state.
#
# Reported as its own line rather than folded into BLOCK, because the reason
# differs and so does what would close it: BLOCK cases need a feature, these
# need queues to exist. An incidental `enqueue_workflow` is NOT in this class --
# it becomes a plain start and ports fine, which is why the pattern matches
# assertions and queue-only APIs rather than any mention of a queue.
SEMANTICS = re.compile(r'WorkflowStatusString\.(ENQUEUED|DELAYED)'
                       r'|enqueue_workflow_with_options|retrieve_queue|list_queues'
                       r'|register_queue\w*\(.*polling|delay_seconds')


def _module_constants(tree):
    """Top-level literal assignments, so a parametrize can name its list."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            try:
                out[n.targets[0].id] = ast.literal_eval(n.value)
            except Exception:
                pass
    return out


def _parametrize_multiplier(dec, consts):
    """How many cases one decorator produces. 1 unless it is a parametrize.

    A `@pytest.mark.parametrize("code", [400, 401, 403, 404])` is FOUR
    collected cases, not one. Counting the function instead undercounts, which
    is what this script did until 2026-09-08 -- and it mattered most on the one
    file whose figure was believed verified: test_queue.py is 91 cases from 77
    functions.

    Returns 1 for a shape this cannot evaluate (a fixture-generated list, a
    generator) rather than guessing, so an unknown under-counts loudly in the
    direction that is already documented rather than inventing a number.
    """
    if not isinstance(dec, ast.Call) or "parametrize" not in ast.unparse(dec.func):
        return 1
    if len(dec.args) < 2:
        return 1
    vals = dec.args[1]
    try:
        return max(1, len(ast.literal_eval(vals)))
    except Exception:
        pass
    if isinstance(vals, ast.Name) and vals.id in consts:
        return max(1, len(consts[vals.id]))
    return 1


def collected(path):
    """The (qualified_name, node) pairs pytest would collect from `path`.

    A parametrized function appears once per case, named `f[0]`, `f[1]`, ... --
    not the real ids pytest generates, but the right CARDINALITY, which is what
    every caller here counts.
    """
    tree = ast.parse(open(path).read())
    consts = _module_constants(tree)
    out = []

    def add(qual, node):
        mult = 1
        for d in node.decorator_list:
            mult *= _parametrize_multiplier(d, consts)
        if mult == 1:
            out.append((qual, node))
        else:
            out.extend((f"{qual}[{i}]", node) for i in range(mult))

    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
            add(n.name, n)
        elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test_"):
                    add(f"{n.name}::{m.name}", m)
    return out


def main(up, ports):
    fns = collected(up)
    print(f"{up}: {len(fns)} collectible cases")
    blocked, have, plain = [], [], []
    for q, n in fns:
        s = ast.unparse(n)
        (blocked if BLOCK.search(s) else have if HAVE.search(s) else plain).append(q)
    portable = have + plain
    src = {q: ast.unparse(n) for q, n in fns}
    semantic = [q for q in portable if SEMANTICS.search(src[q])]
    print(f"  needs a control cleat lacks : {len(blocked)}")
    print(f"  needs only priority/dedup   : {len(have)}")
    print(f"  needs no queue control      : {len(plain)}")
    print(f"  ...of those, needs queue SEMANTICS cleat lacks : {len(semantic)}")
    print(f"  => plausibly portable       : {len(portable) - len(semantic)}"
          f"  ({len(portable)} before removing the semantics cases)")
    total = 0
    for pf in ports:
        fs = collected(pf)
        sk = [q for q, n in fs if any('skip' in ast.unparse(d) for d in n.decorator_list)]
        total += len(fs)
        print(f"{pf}: {len(fs)} cases ({len(fs) - len(sk)} active, {len(sk)} skipped)")
    if ports:
        print(f"  ported total: {total}")
    print("\nPORTABLE (work-list):")
    for q in sorted(set(portable) - set(semantic)):
        print("  ", q)
    if semantic:
        print("\nNEEDS QUEUE SEMANTICS (not portable, distinct from the controls above):")
        for q in sorted(semantic):
            print("  ", q)


# ---------------------------------------------------------------------------
# Inventory generation (--inventory / --check)
#
# README.md's two tables were hand-maintained and drifted: eight cases across
# four files, plus four port files missing from the second table entirely, plus
# a Ported column whose cells, stated total and the tree gave three different
# answers. Correcting cells by hand only resets that clock, so the tables are
# generated from the tree and CI checks the file matches.
# ---------------------------------------------------------------------------

#: Upstream case counts, measured BY COLLECTION at the pinned ref -- not by
#: grep. Every figure the README carried before this was `grep -c 'def test_'`,
#: which counts helper functions defined inside test bodies; that reproduces
#: all eight old values exactly, which is how the method was identified rather
#: than guessed. Three rows did not move, which is why the old numbers looked
#: plausible: the inflation is concentrated in the files that declare inner
#: workflows and steps.
#:
#: Measured 2026-09-08 at PIN 833794f7a1138bacf75ff6d88647a33eb5e35e52, with
#: parametrize EXPANDED -- a `@parametrize("code", [400, 401, 403, 404])` is
#: four collected cases. Three figures here exceed their function count for
#: that reason: test_queue.py 77 -> 91, test_client.py 54 -> 57,
#: test_workflow_management.py 44 -> 46, test_async.py 32 -> 33. Two of those
#: raised a number that had gone DOWN in the same change, which is why the
#: direction of a correction is not evidence about it.
#: Re-derive (needs network, which is why the values are pinned here rather
#: than fetched at generation time -- CI runs this check without egress):
#:
#:   PIN=833794f7a1138bacf75ff6d88647a33eb5e35e52
#:   for f in test_queue test_failures test_workflow_management test_concurrency \
#:            test_dbos test_async test_scheduler test_client; do
#:     curl -sSL https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/$PIN/tests/$f.py -o /tmp/$f.py
#:     python3 scripts/count-queue-cases.py /tmp/$f.py | head -1
#:   done
UPSTREAM = [
    # (file, collected cases, priority text, was-grep-value)
    ("test_queue.py", 91, "**1** \u2014 concurrency limits, rate limits, dedup, priority", 103),
    ("test_failures.py", 37, "**1** \u2014 retries, error classification, recovery", 43),
    ("test_workflow_management.py", 46, "**1** \u2014 cancel, resume, fork, list, delete", 44),
    ("test_concurrency.py", 11, "**1** \u2014 concurrent execution and isolation", 21),
    ("test_dbos.py", 61, "2 \u2014 broad core surface, mixed with SDK ergonomics", 138),
    ("test_async.py", 33, "3 \u2014 a third of it asserts nothing about an engine; "
     "read case by case, 1 is portable. See the note below", 57),
    ("test_scheduler.py", 35, "2 \u2014 cron and scheduled workflows", 35),
    ("test_client.py", 57, "3 \u2014 client API surface, largely DBOS-specific", 54),
]

#: Which upstream file each of our test modules is answering. Judgement, so it
#: lives here in one reviewable place -- but the COUNTS beside it are collected
#: from the tree, which is the half that drifted.
#:
#: None means cleat-specific with no upstream analogue; those cases are real
#: coverage and are reported, but they cannot be credited against an upstream
#: file without inflating that file's Ported figure.
MAPPING = {
    "test_concurrency.py": ("test_queue.py", "concurrency keys are cleat's dedup surface"),
    "test_queues.py": ("test_queue.py", "deduplication by Idempotency-Key, priority accepted"),
    "test_locks.py": ("test_queue.py", "serialising work through a held key"),
    "test_priority_order.py": ("test_queue.py", "priority is a queue control"),
    "test_run_metadata.py": ("test_dbos.py",
                             "a repeat start is deduplication rather than recovery, "
                             "and the run's own clock is ordered"),
    "test_retries.py": ("test_failures.py", ""),
    "test_recovery.py": ("test_failures.py", "recovery counts after a crash"),
    "test_dead_letters.py": ("test_failures.py", "retries exhausted, and what is retained"),
    "test_cancellation.py": ("test_workflow_management.py", ""),
    "test_detached.py": ("test_workflow_management.py", "the nearest thing cleat has to fork"),
    "test_workflow_management.py": ("test_workflow_management.py",
                                    "force-complete, force-fail, and their refusals"),
    "test_children.py": ("test_concurrency.py", "concurrent execution and isolation"),
    "test_parallelism.py": ("test_async.py",
                            "the one portable case: workflows actually run at once"),
    # The other half of upstream test_concurrency.py, and the only half of it
    # that is portable: nine of its eleven cases drive asyncio.gather inside one
    # workflow, which the determinism analyzer refuses at build time (ISSUES 22).
    "test_identity_isolation.py": ("test_concurrency.py",
                                   "a run reports its own id under concurrency"),
    "test_complex_args.py": ("test_queue.py",
                             "upstream test_complex_type -- a nested struct argument "
                             "survives the store, including across a suspension"),
    "test_timeouts.py": ("test_queue.py",
                         "upstream test_unsetting_timeout -- a per-run deadline "
                         "and whether a child inherits it; skipped, ISSUES.md 25"),
    "test_executor_identity.py": ("test_queue.py",
                                  "upstream test_queue_executor_id -- which worker ran a "
                                  "completed run; skipped, ISSUES.md 26"),
    "test_replay.py": ("test_dbos.py", ""),
    "test_send.py": ("test_dbos.py", "`send` delivery semantics"),
    "test_promises.py": ("test_dbos.py", "`set_event`/`get_event`"),
    # None, not test_dbos.py. This module ports nothing: its docstring is
    # "Does the promise wake path have cleat#953's defect?", and "promise"
    # appears zero times in upstream's test_dbos.py -- DBOS has no promise
    # primitive at all. Crediting it upstream would count coverage of a file
    # these cases take nothing from, inflating Ported in the flattering
    # direction. Corrected in review before it shipped.
    "test_promise_wakes.py": (None, "cleat-specific: does the promise wake path "
                              "share cleat#953's defect"),
    "test_signals.py": ("test_dbos.py", "`recv` with a timeout, and `send` between workflows"),
    "test_determinism.py": ("test_dbos.py", "stable IDs and randomness under recovery"),
    "test_continue_as_new.py": ("test_dbos.py", "bounded history via self-restart"),
    "test_defer.py": ("test_dbos.py", "cleanup that runs once though the body runs twice"),
    "test_query_state.py": ("test_dbos.py", "workflow status readable while running"),
    "test_scheduling.py": ("test_scheduler.py", "cron and delayed invocation"),
    "test_schedule_timezones.py": ("test_scheduler.py", "cron zones and the default zone"),
    "test_misfire.py": ("test_scheduler.py", "firings missed during an outage \u2014 "
                        "upstream calls it backfill, cleat calls it misfire_policy"),
    # SPANS TWO UPSTREAM FILES, and this mapping assigns it wholly to one.
    # Two of its cases exercise list_workflows, which is a workflow-management
    # operation -- test_workflow_management.py's own description names "list".
    # Not split, because hand-splitting a module across rows is what produced
    # the drift this generator replaces. But the consequence is recorded rather
    # than left implicit: the TOTAL is right and the DISTRIBUTION is off by two
    # between these rows. This is the standing cost of per-module mapping, and
    # any module that spans two upstream files pays it.
    "test_idempotency_key_form.py": ("test_client.py", "upstream test_client_enqueue_"
                                    "rejects_empty_workflow_id -- a blank identifier must "
                                    "not become a real one"),
    "test_api_surface.py": ("test_client.py", "the HTTP surface a client drives; "
                            "two of its cases are arguably workflow-management"),
    "test_results.py": ("test_failures.py",
                        "upstream's test_nonserializable_return; the property generalises "
                        "past pickle, and cleat substitutes rather than failing"),
    "test_plugins.py": (None, "cleat has no upstream analogue; plugin calls through a real worker"),
    "test_versions.py": (None, "cleat-specific version reporting across a suspension"),
    # None, and deliberately so. Upstream has no cross-process case to port:
    # DBOS DEFERS a task blocked by a concurrency limit and runs it when the
    # limit frees, so its assertions are about queueing. cleat REFUSES with a
    # 409, because ConcurrencyKey is a mutex -- key_hash as PRIMARY KEY with
    # ON CONFLICT DO NOTHING (ISSUES.md #20). Crediting these against
    # test_queue.py would count coverage of a file whose cases assert the
    # opposite behaviour.
    "test_cross_worker.py": (None, "cleat-specific: mutual exclusion across two "
                             "worker PROCESSES, which needs the second_worker "
                             "fixture and has no upstream analogue"),
}


def port_counts(tests_dir):
    """{module: (n_collected, n_skipped)} for our own suite, from the tree.

    Skips are reported because a skipped case is not coverage, and the figure
    was previously a hand-written footnote that said "9 active and 1 skipped"
    against a cell that had since moved to 12.
    """
    import glob, os
    out = {}
    for f in sorted(glob.glob(os.path.join(tests_dir, "test_*.py"))):
        cases = collected(f)
        # Decorator skips only. A conditional pytest.skip() inside a body
        # is deliberately NOT counted: those are written to skip on a defect
        # and assert in full otherwise, so one becomes a passing case the day
        # the defect is fixed, without anyone editing it. Counting them as
        # "skipped" would understate coverage and would go stale silently --
        # test_dead_letters.py has exactly one, and it started passing when
        # cleat#979 was fixed.
        skipped = sum(1 for _, n in cases
                      if any("skip" in ast.unparse(d) for d in n.decorator_list))
        out[os.path.basename(f)] = (len(cases), skipped)
    return out


def inventory(tests_dir):
    counts = port_counts(tests_dir)
    unmapped = sorted(set(counts) - set(MAPPING))
    if unmapped:
        raise SystemExit(
            "these test modules are not in MAPPING, so the tables would silently "
            "under-report them -- add each one:\n  " + "\n  ".join(unmapped))
    ported = {}
    for mod, (n, _) in counts.items():
        up = MAPPING[mod][0]
        if up:
            ported[up] = ported.get(up, 0) + n

    L = []
    # This table is hand-authored constants only -- upstream file, its case
    # count, and our priority. It deliberately has NO column derived from our
    # own tree, and there used to be one ("Cases here"), removed for two
    # independent reasons that happen to point the same way.
    #
    # It collided. It aggregated across every module mapping to an upstream
    # file, so ANY new test rewrote the row for that file -- measured on
    # ports#127 vs #132, where `test_dbos.py` read 22 on one side and 23 on the
    # other and git could not merge them. Unlike a per-module row, which its
    # author owns, this cell had as many authors as the file had mappings.
    #
    # And it misled. Beside a `Cases` column it read as a coverage ratio, which
    # it never was: seven of this port's modules map to test_queue.py, and
    # three of them -- locks, priority order, executor identity -- assert
    # cleat-specific behaviour with no upstream case at all. So "19 of 91" was
    # wrong in both directions at once. It counted cases covering nothing
    # upstream, and said nothing about how many of the 91 were covered.
    #
    # Noticed because a work-list said "19 plausibly portable" and this column
    # said "19" -- two different measurements, equal by coincidence, and the
    # coincidence read as confirmation.
    L.append("| Upstream file | Cases | Priority |")
    L.append("|---|---:|---|")
    for f, n, prio, _ in UPSTREAM:
        L.append(f"| `tests/{f}` | {n} | {prio} |")
    # NO TOTALS ROW, and that is the point rather than an omission.
    #
    # Every per-file row is owned by whoever last touched that upstream file,
    # so two people working on different files rewrite different lines and git
    # merges them. A totals row is rewritten by EVERY test anyone adds, so it
    # is the one line that collides every time -- and it did, ~20% of the
    # pull requests here touch this file. That is the same defect the per-entry
    # split fixed for ISSUES.md and WORKLIST.md, surviving in the one aggregate
    # that stayed generated-and-stored.
    #
    # The totals are derived, so they are derived on demand: --check computes
    # and prints them, and CI shows them on every run. A reader who wants the
    # sum runs the command; a reader who wants to know about one upstream file
    # -- which is what anyone actually asks -- reads its row.
    L.append("")
    L.append("| This suite | Cases | Mapped to |")
    L.append("|---|---:|---|")
    for mod in sorted(counts):
        up, note = MAPPING[mod]
        where = f"`{up}`" if up else "none"
        tail = (" \u2014 " + note) if note else ""
        n, sk = counts[mod]
        cell = f"{n}" + (f" ({sk} skipped)" if sk else "")  # decorator skips only
        L.append(f"| `{mod}` | {cell} | {where}{tail} |")
    return "\n".join(L)


def totals(tests_dir):
    """The figures that used to be stored as two table rows.

    Derived and printed rather than committed, for the reason in inventory():
    a stored aggregate is rewritten by every contribution and so collides with
    every other. Takes tests_dir rather than precomputed counts so that no
    caller can pass it a stale pair.
    """
    counts = port_counts(tests_dir)
    ported = {}
    for mod, (n, _) in counts.items():
        up = MAPPING[mod][0]
        if up:
            ported[up] = ported.get(up, 0) + n
    tot = sum(n for n, _ in counts.values())
    tsk = sum(sk for _, sk in counts.values())
    mapped = sum(ported.values())
    return (f"in scope {sum(n for _, n, _, _ in UPSTREAM)} upstream cases; "
            f"this suite has {tot} ({tsk} skipped outright), "
            f"{mapped} mapped to an upstream file and {tot - mapped} cleat-specific")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ("--inventory", "--check"):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        table = inventory(os.path.join(here, "tests"))
        if sys.argv[1] == "--inventory":
            print(table)
            print()
            print("totals (derived, deliberately not stored):",
                  totals(os.path.join(here, "tests")))
        else:
            readme = open(os.path.join(here, "README.md")).read()
            missing = [ln for ln in table.split("\n")
                       if ln.startswith("|") and ln not in readme]
            if missing:
                raise SystemExit(
                    "README.md's inventory tables no longer match the tree. "
                    "Regenerate with:\n"
                    "    python3 ports/dbos-transact-py/scripts/count-queue-cases.py --inventory\n"
                    "and paste both tables in. Rows that differ:\n  "
                    + "\n  ".join(missing))
            # --check was one-directional: it confirmed every GENERATED line
            # was present, and said nothing about lines present but not
            # generated. A stale row therefore survived silently, and that is
            # not hypothetical -- during a rebase `--ours` is upstream and
            # `--theirs` is the commit being replayed, inverted from what the
            # words suggest, so a resolution that looks right can regenerate on
            # top of the wrong side and keep a row for a module no longer in
            # the tree.
            #
            # Scoped to the generated blocks by their header lines: this README
            # has OTHER tables whose rows also begin "| `test_", written by
            # hand -- upstream file statistics, and the named cases we have
            # judged unportable. Checking the whole file flags all of those.
            for tbl in table.split("\n\n"):
                rows = [ln for ln in tbl.split("\n") if ln.startswith("|")]
                if len(rows) < 2:
                    continue
                hdr = rows[0]
                m = re.search(re.escape(hdr) + r"\n\|[-: |]+\n((?:\|[^\n]*\n)*)",
                              readme)
                if not m:
                    continue  # the missing-line check above already reports this
                present = [ln for ln in m.group(1).split("\n") if ln.startswith("|")]
                stale = [ln for ln in present if ln not in rows]
                if stale:
                    raise SystemExit(
                        "README.md's inventory has rows the generator did not "
                        "produce, so they describe modules that are not in the "
                        "tree -- usually a conflict resolved by merging a "
                        "generated file instead of regenerating it. "
                        "Regenerate with --inventory. Stale rows:\n  "
                        + "\n  ".join(stale))
            stored = [ln for ln in readme.split("\n")
                      if ln.startswith("| **Total")]
            if stored:
                raise SystemExit(
                    "README.md has a stored totals row again. Totals are "
                    "derived, and a stored aggregate is rewritten by every "
                    "contribution, so it is the one line every concurrent "
                    "branch collides on -- which is why it was removed. Delete "
                    "these rows; --check and --inventory both print the "
                    "figures:\n  " + "\n  ".join(stored))
            print("README.md inventory tables match the tree")
            # The totals live here rather than in the file, so CI reports them
            # on every run and no contribution has to rewrite a shared line.
            print("totals:", totals(os.path.join(here, "tests")))
    else:
        main(sys.argv[1], sys.argv[2:])
