"""Shared fixtures for the DBOS-derived port.

CLEAT_PORTS_DSN is set by scripts/run-port.sh and points at the PostgreSQL
started by the repo's docker-compose.yml — the same pinned image cleat's own
dev compose uses, so a failure here is never explicable by a database version
difference.
"""

import os

import pytest


@pytest.fixture(scope="session")
def dsn() -> str:
    value = os.environ.get("CLEAT_PORTS_DSN")
    if not value:
        pytest.fail(
            "CLEAT_PORTS_DSN is unset — run this port via `make port PORT=dbos-transact-py` "
            "from the repository root, which starts PostgreSQL and sets it."
        )
    return value
