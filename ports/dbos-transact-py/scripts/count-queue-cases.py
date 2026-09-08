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
BLOCK = re.compile(r'worker_concurrency\s*=|global_concurrency\s*=|\blimiter\s*='
                   r'|partition_\w*\s*=|Queue\(\s*"[^"]*"\s*,\s*\d+|[^_]\bconcurrency\s*=')
# Controls cleat does have.
HAVE  = re.compile(r'priority|deduplication_id|dedup|app_version')


def collected(path):
    """The (qualified_name, node) pairs pytest would collect from `path`."""
    tree = ast.parse(open(path).read())
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
            out.append((n.name, n))
        elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test_"):
                    out.append((f"{n.name}::{m.name}", m))
    return out


def main(up, ports):
    fns = collected(up)
    print(f"{up}: {len(fns)} collectible cases")
    blocked, have, plain = [], [], []
    for q, n in fns:
        s = ast.unparse(n)
        (blocked if BLOCK.search(s) else have if HAVE.search(s) else plain).append(q)
    print(f"  needs a control cleat lacks : {len(blocked)}")
    print(f"  needs only priority/dedup   : {len(have)}")
    print(f"  needs no queue control      : {len(plain)}")
    print(f"  => plausibly portable       : {len(have) + len(plain)}")
    total = 0
    for pf in ports:
        fs = collected(pf)
        sk = [q for q, n in fs if any('skip' in ast.unparse(d) for d in n.decorator_list)]
        total += len(fs)
        print(f"{pf}: {len(fs)} cases ({len(fs) - len(sk)} active, {len(sk)} skipped)")
    if ports:
        print(f"  ported total: {total}")
    print("\nPORTABLE (work-list):")
    for q in sorted(have + plain):
        print("  ", q)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
