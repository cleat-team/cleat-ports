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
        """Start a workflow. `payload` must be a dict keyed by parameter name.

        Entry-point arguments bind by the EXACT Go parameter name, camelCase
        included: `Handle(h, intervalMs int)` takes `{"intervalMs": 400}`, not
        `{"intervalms": ...}`. (An earlier version of this docstring said
        "lowercased", which only looked right because the first workflow's
        parameter was `ms`. A mis-cased key binds nothing and the parameter is
        left at its zero value.)

        One exception, measured: a workflow with a SINGLE string parameter
        receives the raw input JSON instead of a named field, so
        `{"input": {"key": "ABC"}}` arrives as the string `{"key": "ABC"}`.
        testdata/minimal-wf names that parameter `input` for exactly this
        reason. Give such a workflow a second parameter if you want binding by
        name. Passing a bare
        scalar is not an error: unmatched parameters are left at their zero
        value and the run completes normally. Every test in this port was
        briefly passing `{"input": 1500}` and therefore running with ms=0 --
        the assertions still held, but for weaker reasons than they claimed.
        Hence the assertion below rather than a comment: a payload that is not
        a mapping cannot bind to anything, and silently proving less than
        intended is the failure mode worth making impossible.
        """
        assert isinstance(payload, dict), (
            "workflow input must be a dict keyed by parameter name, e.g. "
            f"{{'ms': 1500}}; got {type(payload).__name__}"
        )
        headers = {}
        if concurrency_key:
            headers["Cleat-Concurrency-Key"] = concurrency_key
        return self._req("POST", f"/api/workflows/{name}/start",
                         {"input": payload}, headers)

    def get(self, run_id: str):
        return self._req("GET", f"/api/workflows/{run_id}")

    def cancel(self, run_id: str, reason: str = "port test"):
        return self._req("POST", f"/api/workflows/{run_id}/cancel", {"reason": reason})

    def query(self, run_id: str, key: str):
        return self._req("GET", f"/api/workflows/{run_id}/query?key={key}")

    def poll_query(self, run_id: str, key: str, timeout: float = 15.0):
        """Wait until a query key has a value, and return it.

        Needed because the interesting value is published mid-run: a caller
        that waits for completion first has already missed it.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, body = self.query(run_id, key)
            if status == 200 and body.get("value"):
                return body["value"]
            time.sleep(0.1)
        return None

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


def _build_and_deploy(pkg_name: str, workflow_name: str) -> str:
    """Build one workflow package to WASM and deploy it under a stable name."""
    root = pathlib.Path(__file__).resolve().parents[3]
    pkg = pathlib.Path(__file__).resolve().parents[1] / "workflows" / pkg_name
    out = root / ".port-results" / "wasm" / pkg_name

    built = subprocess.run(
        [str(root / "scripts" / "build-workflow.sh"), str(pkg), str(out)],
        capture_output=True, text=True,
    )
    if built.returncode != 0:
        pytest.fail(f"building {pkg_name} failed:\n{built.stderr[-2000:]}")

    deployed = subprocess.run(
        [str(root / "bin" / "cleat"), "--db", os.environ["CLEAT_PORTS_DSN"],
         "deploy", "--name", workflow_name, built.stdout.strip()],
        capture_output=True, text=True,
    )
    if deployed.returncode != 0:
        pytest.fail(f"deploying {workflow_name} failed:\n{deployed.stderr[-2000:]}")
    return workflow_name


@pytest.fixture(scope="session")
def fanout_workflow(cleat: Cleat) -> str:
    """Deploy both halves of the fan-out pair and return the parent's name.

    The child is deployed first: the parent spawns it by name, so a parent
    deployed against a missing child fails at run time with "start failed"
    rather than at deploy time.
    """
    _build_and_deploy("childleaf", "child_leaf")
    return _build_and_deploy("parentfanout", "fanout")


@pytest.fixture(scope="session")
def fixture_calls():
    """Read the fixture service's per-key call counter.

    Lets a test assert how many times the service was actually reached, which
    is the only direct evidence of a retry -- wall-clock timing shows that
    waiting happened, not that the call was repeated.
    """
    base = os.environ.get("CLEAT_PORTS_FIXTURE_URL", "http://127.0.0.1:8098")

    def count(key: str) -> int:
        with urllib.request.urlopen(f"{base}/calls/{key}", timeout=10) as resp:
            return json.loads(resp.read())["attempts"]

    return count


@pytest.fixture(scope="session")
def detached_workflow(cleat: Cleat, retry_workflow: str) -> str:
    """Deploy the detached-execution workflow.

    Depends on retry_workflow because the detached run IS that workflow: it is
    already deployed, already calls the fixture, and takes a key — so the test
    can observe a detached run without a second fixture-calling workflow.
    """
    return _build_and_deploy("detached", "detached")


@pytest.fixture(scope="session")
def retry_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("retry", "retrycall")


@pytest.fixture(scope="session")
def cancellable_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("cancellation", "cancellable")


@pytest.fixture(scope="session")
def replay_identity_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("replay", "replay_identity")


@pytest.fixture(scope="session")
def continue_as_new_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("continueasnew", "continue_as_new")


@pytest.fixture(scope="session")
def signal_pair(cleat: Cleat) -> tuple[str, str]:
    """Deploy the signal receiver and sender, returning both names."""
    receiver = _build_and_deploy("signalreceiver", "signal_receiver")
    sender = _build_and_deploy("signalsender", "signal_sender")
    return receiver, sender


@pytest.fixture(scope="session")
def lock_workflows(cleat: Cleat) -> tuple[str, str]:
    """Deploy the lock holder and the lock attempt, returning both names."""
    holder = _build_and_deploy("lockholder", "lock_holder")
    tryer = _build_and_deploy("locktry", "lock_try")
    return holder, tryer


@pytest.fixture(scope="session")
def determinism_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("determinism", "determinism")


@pytest.fixture(scope="session")
def signal_timeout_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("signaltimeout", "signal_timeout")


@pytest.fixture(scope="session")
def promise_workflow(cleat: Cleat) -> str:
    """Deploy the settler first: the parent spawns it by name, so a parent that
    started before the child was deployed would fail on a missing workflow
    rather than on anything this port is testing."""
    _build_and_deploy("promisesettler", "promise_settler")
    return _build_and_deploy("promiseparent", "promise_parent")


@pytest.fixture(scope="session")
def send_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("send", "send")


@pytest.fixture(scope="session")
def recovery_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("recovery", "recovery")


@pytest.fixture(scope="session")
def defer_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("defercleanup", "defer_cleanup")


@pytest.fixture(scope="session")
def send_after_sleep_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("sendaftersleep", "send_after_sleep")


@pytest.fixture(scope="session")
def worker():
    """Crash and restart the shared worker.

    The worker is shared by every port in a run, so a test that kills it is
    borrowing something the rest of the suite needs back. `restart` is
    therefore not optional cleanup -- it is part of the operation, and the
    fixture restarts on teardown as well in case a test fails between the two.

    `crash` is SIGKILL. A graceful stop lets the worker release its claims,
    which would make a recovery test into a shutdown test: the interesting
    state is a workflow still marked running, owned by a worker that is never
    coming back, which only an ungraceful death produces.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    script = str(root / "scripts" / "worker.sh")

    def run(action: str) -> None:
        done = subprocess.run([script, action], capture_output=True, text=True)
        if done.returncode != 0:
            pytest.fail(f"worker.sh {action} failed:\n{done.stderr[-2000:]}")

    class Worker:
        def crash(self) -> None:
            run("crash")

        def restart(self) -> None:
            run("ensure")

    w = Worker()
    yield w
    # Whatever the test did, the next one needs a worker.
    w.restart()


@pytest.fixture(scope="session")
def holds_key_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("concurrency", "holds_key")
