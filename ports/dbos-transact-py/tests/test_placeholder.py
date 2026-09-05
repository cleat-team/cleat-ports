"""Placeholder so the port's harness is exercised before any test is ported.

Delete this file with the first real ported test. It exists only to prove the
plumbing — venv, SDK install, database, cleat toolchain — works, so that the
first genuine failure is about cleat rather than about setup.
"""


def test_harness_runs(dsn: str) -> None:
    assert dsn.startswith("postgres://")
