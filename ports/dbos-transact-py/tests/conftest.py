"""Shared fixtures for the DBOS-derived port.

CLEAT_PORTS_DSN is set by scripts/run-port.sh and points at the PostgreSQL
started by the repo's docker-compose.yml — the same pinned image cleat's own
dev compose uses, so a failure here is never explicable by a database version
difference.
"""

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

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

@pytest.fixture(scope="session")
def api(dsn: str) -> str:
    """Base URL of the one cleat worker shared by every port in this run.

    Started by scripts/worker.sh via run-port.sh, torn down by the Makefile's
    trap. Deliberately one worker rather than one per port: cleat enforces its
    concurrency key in the database, so a concurrency assertion is still
    correct with several workers, but "did the second run start" becomes a
    question about which worker polled first, and a test whose meaning depends
    on that is not measuring what it claims to.
    """
    value = os.environ.get("CLEAT_PORTS_API")
    if not value:
        pytest.fail(
            "CLEAT_PORTS_API is unset — run this port via `make port PORT=dbos-transact-py` "
            "from the repository root, which starts the shared worker and sets it."
        )
    return value

@pytest.fixture(scope="session")
def api_key() -> str:
    value = os.environ.get("CLEAT_PORTS_API_KEY")
    if not value:
        pytest.fail("CLEAT_PORTS_API_KEY is unset — run via `make port PORT=dbos-transact-py`.")
    return value


class Cleat:
    """The smallest client these ports need, over urllib rather than requests.

    Deliberately not a wrapper that raises on non-2xx: several assertions here
    are *about* the status code — a rejected start is the behaviour under test,
    not an error — and a client that treats 409 as an exception would make the
    interesting case the hard one to write.
    """

    def __init__(self, base: str, key: str) -> None:
        self.base = base.rstrip("/")
        self.key = key

    def _req(self, method: str, path: str, body: dict | None = None,
             headers: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"body": raw.decode(errors="replace")[:200]}

    def start(self, name: str, payload, concurrency_key: str | None = None):
        headers = {}
        if concurrency_key:
            headers["Cleat-Concurrency-Key"] = concurrency_key
        return self._req("POST", f"/api/workflows/{name}/start",
                         {"input": payload}, headers)

    def get(self, run_id: str):
        return self._req("GET", f"/api/workflows/{run_id}")

    def await_terminal(self, run_id: str, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            _, last = self.get(run_id)
            if last.get("status") in ("done", "failed", "terminated", "cancelled"):
                return last
            time.sleep(0.2)
        pytest.fail(f"run {run_id} did not reach a terminal status within "
                    f"{timeout}s; last status {last.get('status')!r}")


@pytest.fixture(scope="session")
def cleat(api: str, api_key: str) -> Cleat:
    return Cleat(api, api_key)


@pytest.fixture(scope="session")
def holds_key_workflow(cleat: Cleat) -> str:
    """Build and deploy the workflow these tests drive, and return its name.

    Session-scoped and idempotent: deploying the same name again adds a version
    rather than failing, so a re-run costs a build but never a stale binary.
    """
    # tests/ -> dbos-transact-py/ -> ports/ -> repo root
    root = pathlib.Path(__file__).resolve().parents[3]
    pkg = pathlib.Path(__file__).resolve().parents[1] / "workflows" / "concurrency"
    out = root / ".port-results" / "wasm" / "concurrency"

    built = subprocess.run(
        [str(root / "scripts" / "build-workflow.sh"), str(pkg), str(out)],
        capture_output=True, text=True,
    )
    if built.returncode != 0:
        pytest.fail(f"building the workflow failed:\n{built.stderr[-2000:]}")
    wasm = built.stdout.strip()

    deployed = subprocess.run(
        [str(root / "bin" / "cleat"), "--db", os.environ["CLEAT_PORTS_DSN"],
         "deploy", "--name", "holds_key", wasm],
        capture_output=True, text=True,
    )
    if deployed.returncode != 0:
        pytest.fail(f"deploying the workflow failed:\n{deployed.stderr[-2000:]}")
    return "holds_key"
