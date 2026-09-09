"""Shared fixtures for the DBOS-derived port.

CLEAT_PORTS_DSN is set by scripts/run-port.sh and points at the PostgreSQL
started by the repo's docker-compose.yml — the same pinned image cleat's own
dev compose uses, so a failure here is never explicable by a database version
difference.
"""

import json
import os
import pathlib
import re
import subprocess
import uuid
import time
import urllib.error
import urllib.request

import pytest


# Entry-point parameters, per deployed workflow name, filled in by
# _build_and_deploy. Cleat.start refuses a payload that omits one.
#
# WHY THIS EXISTS. An omitted parameter is not an error. A workflow started
# without one runs anyway, with that parameter at its zero value, and every
# assertion that does not depend on it still passes -- so the test goes green
# while measuring something weaker than its name claims. Cleat.start's docstring
# already records one round of this: every test in this port was briefly passing
# {"input": 1500} and therefore running with ms=0. This is that warning made
# enforceable.
#
# The hazard is permanent and the sixteen omissions it found were three years'
# worth of nobody checking, but what surfaced them was a two-hour window in
# which cleat#1046 made an absent INT a hard decode error rather than a zero.
# Measured then, one machine, one worker, varying only the guest codegen:
#
#   absent parameter   normally     during that window
#   string             binds ""     binds ""
#   int                binds 0      unmarshal <name>: unexpected end of JSON input
#   struct             error        error
#
# cleat#1057 restored the int column. The row that matters here is the first
# one, which never changed: an absent STRING has always bound "" silently, and
# always will.
#
# Eight of the sixteen went red in that window. THE OTHER EIGHT ARE THE REASON
# FOR A GUARD RATHER THAN SIXTEEN CORRECTED PAYLOADS. They kept passing, because
# a run that binds nothing still appears in a list, still has an empty event
# collection, and still answers a force-complete. They asserted API shape around
# a workflow body that never executed -- and four of them are named for what
# happens to a RUNNING workflow, which that run had already stopped being.
#
# So the omission was survivable in exactly the cases where it hollowed the test
# out. A green suite could not distinguish them from the eight that failed
# loudly, and neither could a reader.
#
# The registry is derived from the Go signature at deploy time rather than
# maintained by hand, so a parameter added to a workflow is enforced at every
# call site from the moment it exists.
_ENTRY_PARAMS: dict[str, list[str]] = {}

_SIG = re.compile(r'^func\s+[A-Z]\w*\(h cleat\.HostCalls,?\s*([^)]*)\)', re.M)


def _entry_params(pkg_dir: pathlib.Path) -> list[str] | None:
    """Parameter names of a workflow package's entry point, in order.

    Returns None when the payload does not bind by name at all: an entry point
    whose ONLY parameter is a string receives the raw input JSON instead
    (wasm/exports.go, `len(fields) == 1 && fields[0].GoType == "string"`), so
    for those a "missing parameter" is not a meaningful thing to check.
    """
    src = (pkg_dir / "main.go").read_text()
    m = _SIG.search(src)
    if not m:
        return None
    fields = []
    for part in m.group(1).split(","):
        toks = part.split()
        if len(toks) == 2:
            fields.append((toks[0], toks[1]))
        elif len(toks) == 1 and toks[0]:
            # `a, b string` -- type belongs to the last name in the group.
            fields.append((toks[0], None))
    if not fields:
        return None
    if len(fields) == 1 and fields[0][1] == "string":
        return None
    return [name for name, _ in fields]


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


# Distinguishes "no input field in the request" from "input: {}". See
# create_schedule -- the two are different requests and cleat#997 was the
# difference.
_OMIT = object()


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

    def start(self, name: str, payload, concurrency_key: str | None = None,
              idempotency_key: str | None = None, priority: int | None = None):
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
        omitted = [p for p in _ENTRY_PARAMS.get(name, []) if p not in payload]
        assert not omitted, (
            f"start({name!r}) omits {', '.join(omitted)}, which the entry point "
            f"declares. Pass every parameter explicitly. An omitted parameter "
            f"binds its zero value and the run completes, so the assertions "
            f"below will most likely still pass -- against a workflow that did "
            f"not receive what this test meant to give it. See _ENTRY_PARAMS."
        )
        headers = {}
        if concurrency_key:
            headers["Cleat-Concurrency-Key"] = concurrency_key
        if idempotency_key:
            # A HEADER, not a body field. The start handler reads
            # r.Header.Get("Idempotency-Key") (cmd/cleat-worker/server.go:515)
            # while priority comes from the JSON body -- the two queue controls
            # arrive by different routes, which is worth knowing before
            # debugging why one of them appears to be ignored.
            headers["Idempotency-Key"] = idempotency_key
        body = {"input": payload}
        if priority is not None:
            body["priority"] = priority
        return self._req("POST", f"/api/workflows/{name}/start", body, headers)

    def get(self, run_id: str):
        return self._req("GET", f"/api/workflows/{run_id}")

    def api(self, path: str):
        """GET any API path, for endpoints without a dedicated helper.

        The per-run sub-resources are split across TWO prefixes, which is not
        guessable and costs a 404 to discover:

            /api/instances/{id}/events    /api/instances/{id}/state
            /api/workflows/{id}/history   /api/workflows/{id}/promises
            /api/workflows/{id}/dag

        Measured, not read off the route table -- `/api/workflows/{id}/events`
        and `/api/instances/{id}/history` both answer 404.
        """
        return self._req("GET", path)

    def dead_letters(self):
        return self._req("GET", "/api/dead-letters")

    def dlq_op(self, run_id: str, op: str):
        """reprocess or terminate a dead-lettered run.

        Under /api/dead-letters/, NOT /api/workflows/ -- the latter 404s for
        both. There is also a /api/workflows/{id}/retry, which is a different
        endpoint answering 400 "workflow is not dead-lettered" for a live run.
        """
        return self._req("POST", f"/api/dead-letters/{run_id}/{op}", {})

    def signal(self, run_id: str, signal_name: str, payload: str = "{}"):
        """Deliver a signal over HTTP.

        The body field is `signal_name`, not `name`; `name` is a 400 that says
        `signal_name is required`, which is clear once seen and invisible
        beforehand.
        """
        return self._req("POST", f"/api/workflows/{run_id}/signal",
                         {"signal_name": signal_name, "payload": payload})

    def admin(self, run_id: str, op: str, body: dict | None = None,
              confirm: str | None = None):
        """Call an operator endpoint on a run.

        Two things this signature exists to make visible, both of which cost
        time to rediscover from a 400:

        - The confirmation header's VALUE is the operation name, not a constant:
          `X-Confirm: force-complete`. A wrong value is a 400 that says so.
        - These live under `/api/admin/instances/`, a different prefix from
          `/api/workflows/`. Seven of these routes were once registered on a
          table the binary never served, and the symptom was the SPA's HTML
          fallback at 200 rather than a 404 (cleat#830) -- so a test here
          should assert on the status, not merely that something came back.
        """
        headers = {"X-Confirm": confirm if confirm is not None else op}
        return self._req("POST", f"/api/admin/instances/{run_id}/{op}",
                         body if body is not None else {}, headers)

    def cancel(self, run_id: str, reason: str = "port test"):
        return self._req("POST", f"/api/workflows/{run_id}/cancel", {"reason": reason})

    def create_schedule(self, name: str, cron: str, def_name: str,
                        entry_point: str = "", inp=_OMIT, misfire: str = "",
                        catch_up_limit: int = 0, overlap_policy: str = "",
                        timezone: str = ""):
        """POST /api/schedules -- the operator path.

        The scheduling tests that use h.ScheduleCron go in through GUEST code,
        which carries none of the three policy fields. This is the only way to
        set one at all.

        misfire is passed through verbatim, including "" -- which the engine
        reads as catch_up (engine/cron.go: "Empty is valid and means
        MisfireCatchUp"). A test that wants the DEFAULT must be able to send
        nothing rather than send the default's name, or it tests the name.

        inp defaults to the _OMIT sentinel rather than to {} because those are
        different requests, and the difference was a bug: omitting "input"
        entirely used to answer 500, since workflow_schedules.input is
        NOT NULL DEFAULT '{}' and a column default does not apply to an INSERT
        that names the column (cleat#997). Sending {} never exercised it.

        timezone is the IANA zone the cron's wall-clock fields are read in.
        Sent only when non-empty, for the same reason misfire is: "" and the
        default's NAME are different requests. The engine reads "" as
        DefaultScheduleTimezone and the stores write 'UTC' rather than '', so a
        test that wants to know what omitting DOES must be able to omit.
        """
        body = {"name": name, "cron": cron, "def_name": def_name}
        if entry_point:
            body["entry_point"] = entry_point
        if inp is not _OMIT:
            body["input"] = inp
        if misfire:
            body["misfire_policy"] = misfire
        if catch_up_limit:
            body["catch_up_limit"] = catch_up_limit
        if overlap_policy:
            body["overlap_policy"] = overlap_policy
        if timezone:
            body["timezone"] = timezone
        return self._req("POST", "/api/schedules", body)

    def schedules(self):
        """List cron schedules. Used by the scheduling tests."""
        return self._req("GET", "/api/schedules")


    def delete_schedule(self, name: str):
        return self._req("DELETE", f"/api/schedules/{name}")

    def schedule_enabled(self, name: str, enabled: bool):
        """Enable or disable a schedule.

        POST /api/schedules/{name}/enable | /disable, both with no body.
        Separate from delete_schedule because the difference is the point: a
        disabled schedule is retained and can be resumed, a deleted one cannot.
        """
        action = "enable" if enabled else "disable"
        return self._req("POST", f"/api/schedules/{name}/{action}", {})
    def resolve_promise(self, run_id: str, promise_id: str, result: str = "{}"):
        """Resolve a promise from outside the workflow.

        Under /api/workflows/{runID}/promises/{promiseID}/resolve. The run id is
        the OWNING workflow, not the promise's own -- the promise id alone is
        not addressable.
        """
        return self._req("POST",
                         f"/api/workflows/{run_id}/promises/{promise_id}/resolve",
                         {"result": result})

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

    #: The statuses a run can settle in, taken from the engine rather than
    #: assumed: cmd/cleat-worker/server.go's isTerminalStatus.
    #:
    #: "dead_lettered" was missing, so a dead-lettered run -- which is settled,
    #: and is the whole point of the dead-letter tests -- could never satisfy
    #: this loop. It polled a finished run until the deadline and then failed
    #: with a message naming the terminal status it had spent 60s waiting for.
    #:
    #: "cancelled" was present and is NOT a workflow status. The engine never
    #: writes it: the cancel endpoint returns {"status": "cancellation_
    #: requested"} as an API response field, and engine/errors.go's "cancelled"
    #: is an ErrorCode. test_cancellation.py says so in its own module
    #: docstring -- "There is no cancelled terminal status" -- and pins it in
    #: test_a_cancelled_workflow_still_reports_status_done. A cancelled run
    #: ends up "done" or "terminated". Nothing depended on the branch; it never
    #: matched anything.
    #:
    #: Those two are one defect, not two. A set of four names reads as an
    #: enumeration of "the ways a run ends", so nobody counted it against the
    #: engine -- and one of the four was fictional while a real one was absent.
    #:
    #: "terminating" is deliberately NOT here even though isTerminalStatus
    #: includes it. There it means "the outcome is already decided, refuse a
    #: late promise". Here it means the defer phase is still running and the
    #: final status has not been written, so returning it would hand callers a
    #: non-final status and break every `final["status"] == "done"` that
    #: follows an await_terminal.
    TERMINAL = ("done", "failed", "terminated", "dead_lettered")

    def await_terminal(self, run_id: str, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            _, last = self.get(run_id)
            if last.get("status") in self.TERMINAL:
                return last
            time.sleep(0.2)
        pytest.fail(f"run {run_id} did not reach a terminal status within "
                    f"{timeout}s; last status {last.get('status')!r}")


def wait_until(predicate, timeout: float, what: str, interval: float = 0.5) -> None:
    """Poll predicate until it is true, or fail naming what was awaited.

    Seven test modules each carried a byte-identical private copy of this, and
    the copies had drifted from the code they were copied from in one way that
    matters: every one used time.time() where every helper in this file uses
    time.monotonic(). Wall-clock can step -- NTP, a suspend, a manual change --
    and a step backwards silently extends a timeout while a step forwards cuts
    it short. Monotonic cannot. So the duplicates were not merely redundant,
    they were slightly worse than the convention they diverged from, which is
    the tell that they were written from each other rather than from here.

    interval stays a parameter because two of the seven polled at 0.25s and
    five at 0.5s. That difference is not load-bearing -- a shorter interval can
    only find the condition sooner -- but it is preserved exactly rather than
    unified, because the suite needs a database and could not be run to check.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


@pytest.fixture(scope="session")
def cleat(api: str, api_key: str) -> Cleat:
    return Cleat(api, api_key)


def _build_and_deploy(pkg_name: str, workflow_name: str, build_flags: str = "") -> str:
    """Build one workflow package to WASM and deploy it under a stable name."""
    root = pathlib.Path(__file__).resolve().parents[3]
    pkg = pathlib.Path(__file__).resolve().parents[1] / "workflows" / pkg_name
    # Per-run, matching scripts/env.sh: several sessions share this checkout
    # and a flat .port-results/wasm/<pkg> means the last build wins. Both
    # halves have to move together -- if the harness writes here while the
    # worker reads the keyed path, the deploy cannot find its binary.
    results = os.environ.get(
        "CLEAT_PORTS_RESULTS_DIR",
        str(root / ".port-results" / os.environ.get("COMPOSE_PROJECT_NAME", "default")),
    )
    out = pathlib.Path(results) / "wasm" / pkg_name

    env = os.environ.copy()
    if build_flags:
        # Forwarded to `cleat build` by scripts/build-workflow.sh. The only
        # current use is `-version N`, which sets the version embedded in the
        # WASM metadata; cmd/deploy-workflow prefers that over auto-increment,
        # so it is how a test deploys two KNOWN versions of one definition.
        env["CLEAT_PORTS_BUILD_EXTRA_FLAGS"] = build_flags
    built = subprocess.run(
        [str(root / "scripts" / "build-workflow.sh"), str(pkg), str(out)],
        capture_output=True, text=True, env=env,
    )
    if built.returncode != 0:
        pytest.fail(f"building {pkg_name} failed:\n{built.stderr[-2000:]}")

    # deploy-workflow, not `cleat deploy`. The CLI's DB-touching subcommands are
    # PostgreSQL-only and refuse a MySQL or SQL Server DSN on purpose --
    # cmd/cleat/db.go's openPostgresDB says so and names this binary as the one
    # multi-dialect entry point. Used on every dialect rather than only the two
    # that need it: one path exercised everywhere beats a conditional exercised
    # on one dialect and assumed on the others.
    deployed = subprocess.run(
        [str(root / "bin" / "deploy-workflow"),
         "-db", os.environ["CLEAT_PORTS_DSN"],
         "-driver", os.environ.get("CLEAT_PORTS_DIALECT", "postgres"),
         workflow_name, built.stdout.strip()],
        capture_output=True, text=True,
    )
    if deployed.returncode != 0:
        pytest.fail(f"deploying {workflow_name} failed:\n{deployed.stderr[-2000:]}")

    declared = _entry_params(pkg)
    if declared:
        _ENTRY_PARAMS[workflow_name] = declared
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
def fixture_log():
    """Read the fixture service's per-key call log, in arrival order.

    Distinct from fixture_calls, which counts. A count cannot answer an
    ORDERING question -- two workflows starting in either sequence are two
    calls -- so the service records the operation names as they arrive and this
    returns them as "service.operation" strings.

    Added for the priority-dispatch test, which asks which workflows were
    claimed first. Nothing else here needed order until something asked whether
    the claim query's `ORDER BY priority` is observable.
    """
    base = os.environ.get("CLEAT_PORTS_FIXTURE_URL", "http://127.0.0.1:8098")

    def log(key: str) -> list[str]:
        with urllib.request.urlopen(f"{base}/log/{key}", timeout=10) as resp:
            return json.loads(resp.read())["calls"]

    return log


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
def fixture_peak():
    """Read the largest number of calls the fixture held open at once, per key.

    The concurrency analogue of fixture_calls: that one counts how many times
    the service was reached, this one how many of those overlapped. A count
    cannot answer a CONCURRENCY question -- fifty calls made one after another
    and fifty made at once are fifty calls either way.

    This exists so the parallel-execution assertion needs no clock. Upstream's
    test_max_parallel_workflows infers concurrency from wall time (50 workflows
    in under 30s where serial would take 250s), and a threshold between two
    timings is the shape that went wrong in cleat-ports#115. A peak has no
    threshold to tune: a serial engine reports exactly 1.
    """
    base = os.environ.get("CLEAT_PORTS_FIXTURE_URL", "http://127.0.0.1:8098")

    def peak(key: str) -> int:
        with urllib.request.urlopen(f"{base}/peak/{key}", timeout=10) as resp:
            return json.loads(resp.read())["peak"]

    return peak


@pytest.fixture(scope="session")
def detached_workflow(cleat: Cleat, retry_workflow: str) -> str:
    """Deploy the detached-execution workflow.

    Depends on retry_workflow because the detached run IS that workflow: it is
    already deployed, already calls the fixture, and takes a key — so the test
    can observe a detached run without a second fixture-calling workflow.
    """
    return _build_and_deploy("detached", "detached")


@pytest.fixture(scope="session")
def dead_letter_opaque_workflow(cleat: Cleat) -> str:
    """A workflow that exhausts its retries and returns its OWN error text.

    The counterpart to dead_letter_workflow, which wraps with %w. The pair
    isolates one variable: whether the engine's error text survives into the
    workflow's final message.
    """
    return _build_and_deploy("deadletteropaque", "dead_letter_opaque")


@pytest.fixture(scope="session")
def priority_mark_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that records its own claim order."""
    return _build_and_deploy("prioritymark", "priority_mark")


@pytest.fixture(scope="session")
def retry_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("retry", "retrycall")


@pytest.fixture(scope="session")
def own_identity_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that reports the run id the engine gave it."""
    return _build_and_deploy("ownidentity", "own_identity")


@pytest.fixture(scope="session")
def bad_result_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that returns results the store may not accept."""
    return _build_and_deploy("badresult", "badresult")


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
def complex_arg_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("complexarg", "complex_arg")


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
def recovery_parent_workflow(cleat: Cleat) -> str:
    """Deploy the child before the parent, as the fan-out fixture does.

    The parent spawns `retrycall` by name, so a parent deployed against a
    missing child fails at run time with "start failed" rather than at deploy
    time -- and in a recovery test that failure would arrive after a crash and
    read like a recovery defect.
    """
    _build_and_deploy("retry", "retrycall")
    return _build_and_deploy("recoveryparent", "recovery_parent")


@pytest.fixture(scope="session")
def version_marked_workflow(cleat: Cleat) -> str:
    """Deploy ONLY v1 of the definition. The test deploys v2 itself.

    Deliberately not both. A fixture that deployed v1 and v2 up front would
    leave nothing in flight across a version change, and a test named for what
    a running workflow does when a new version lands would be asserting about a
    run that started after both deploys had already happened -- true, green,
    and about something else. Ordering is the subject here, so the test has to
    own it.

    The two versions are separate packages rather than one package built twice,
    because they must differ in what they RETURN, not only in the version they
    carry. One package built twice produces two binaries that behave
    identically and no assertion could tell which executed.

    THE NAME IS UNIQUE PER SESSION, and that is not tidiness. `workflow_defs`
    rows outlive a pytest process: a previous run that deployed v2 leaves it
    there, so a later run's "only v1 is deployed" premise is false before the
    first line executes and a start picks up the newest row. Measured -- this
    test passed once and then failed on the next run against the same database,
    reporting "two" for a run that should have been pinned to v1, which reads
    exactly like an engine defect and was leftover state. A fresh name makes
    each run's version history entirely its own.
    """
    global _VERSION_MARK_NAME
    _VERSION_MARK_NAME = f"version_mark_{uuid.uuid4().hex[:8]}"
    return _build_and_deploy(
        "versionone", _VERSION_MARK_NAME, build_flags="-version 1"
    )


_VERSION_MARK_NAME = ""


def deploy_version_two() -> str:
    """Deploy v2 over the same definition name. Called mid-test, on purpose."""
    assert _VERSION_MARK_NAME, "version_marked_workflow must be requested first"
    return _build_and_deploy(
        "versiontwo", _VERSION_MARK_NAME, build_flags="-version 2"
    )


@pytest.fixture(scope="session")
def defer_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("defercleanup", "defer_cleanup")


@pytest.fixture(scope="session")
def send_after_sleep_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("sendaftersleep", "send_after_sleep")


@pytest.fixture(scope="session")
def cron_workflows(cleat: Cleat) -> str:
    """Deploy the cron target first: the schedule starts it by name."""
    _build_and_deploy("crontarget", "cron_target")
    return _build_and_deploy("cronscheduler", "cron_scheduler")


@pytest.fixture(scope="session")
def schedule_invoke_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("scheduleinvoke", "schedule_invoke")


@pytest.fixture(scope="session")
def promise_chain_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that awaits several promises in sequence."""
    return _build_and_deploy("promisechain", "promise_chain")


@pytest.fixture(scope="session")
def query_state_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("querystate", "query_state")


@pytest.fixture(scope="session")
def await_one_child_workflow(cleat: Cleat) -> str:
    """Deploy the child first: the parent spawns it by name."""
    _build_and_deploy("childleaf", "child_leaf")
    return _build_and_deploy("awaitonechild", "await_one_child")


@pytest.fixture
def worker_without_notify():
    """Restart the shared worker with PostgreSQL LISTEN/NOTIFY disabled.

    `-notify-channel` defaults to `cleat_dispatch`
    (cmd/cleat-worker/config.go:70), so every other test in this suite runs
    with NOTIFY on and the 500ms poll merely behind it. Nothing exercises what
    happens when NOTIFY is unavailable -- and that is the path that carries
    correctness when it is.

    This is function-scoped and restores on teardown, including on failure.
    The worker is SHARED by every test in the run, so a flag left set would
    silently apply to everything that follows -- the hazard test_timeouts.py
    records for `--max-workflow-duration`. Restoration is part of the
    operation, not cleanup.

    Yields the worker's argv, so a test can assert the flag actually took
    rather than trusting that setting the environment variable was enough. A
    restart that did not restart looks exactly like a feature that works.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    script = str(root / "scripts" / "worker.sh")

    def run(action: str, env: dict | None = None) -> None:
        done = subprocess.run([script, action], capture_output=True, text=True,
                              env=env or os.environ.copy())
        if done.returncode != 0:
            pytest.fail(f"worker.sh {action} failed:\n{done.stderr[-2000:]}")

    def argv() -> str:
        """The argv of the worker serving THIS run's API port.

        Not every `cleat-worker` on the machine: several sessions share it,
        and a bare `pgrep -fl cleat-worker` matched four of them here. An
        assertion over that text is satisfied by somebody else's flags, which
        makes it a check that passes for a reason having nothing to do with
        the worker under test. Same discriminator worker.sh's `owned` uses,
        and the one cleat-ports#69 exists to provide: the process serving my
        port, not the process with my binary's name.
        """
        port = os.environ.get("CLEAT_PORTS_API_PORT", "8099")
        done = subprocess.run(["pgrep", "-fl", "cleat-worker"],
                              capture_output=True, text=True)
        mine = [ln for ln in done.stdout.splitlines()
                if f"-api-addr 127.0.0.1:{port}" in ln]
        if len(mine) != 1:
            pytest.fail(
                f"expected exactly one cleat-worker on api port {port}, found "
                f"{len(mine)}:\n" + "\n".join(mine))
        return mine[0]

    env = os.environ.copy()
    # Empty value, not absent: absent means "use the default", which is the
    # channel being on. The two are opposite instructions that look alike.
    env["CLEAT_PORTS_WORKER_EXTRA_FLAGS"] = "-notify-channel="

    run("stop-worker")
    run("ensure", env)
    try:
        yield argv()
    finally:
        run("stop-worker")
        run("ensure")   # os.environ, without the extra flag
        # Verify the RESTORE, not just that two commands exited 0. Everything
        # after this test inherits whatever worker is left here, and a restore
        # that quietly kept -notify-channel= would degrade the rest of the
        # suite into a second NOTIFY-disabled run reporting itself as normal.
        # A restore that does not restore looks exactly like one that worked.
        restored = argv()
        assert "-notify-channel=" not in restored, (
            "the shared worker still carries -notify-channel= after teardown; "
            f"every test after this one is running without NOTIFY. argv: {restored!r}")


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

        def stop(self) -> None:
            """Graceful shutdown, as opposed to crash().

            A test that wants to build a BACKLOG needs the worker gone without
            claims left held, so that the queue's contents are entirely the
            test's doing. crash() would leave whatever was in flight owned by a
            dead worker, which is the right thing for a recovery test and the
            wrong thing here.

            THE API GOES WITH IT. This docstring said until 2026-09-08 that
            "the API keeps accepting starts with no worker running -- they land
            as `ready` rows". That is false here: `cleat-worker` IS the API
            server, so a stopped worker refuses every request with a connection
            refusal. A test that creates work after calling this dies on
            connect, and the error reads like a product defect rather than a
            harness one.

            Nothing had caught it because `test_recovery.py` was the only other
            caller and it crashes and restarts with no request in between -- so
            the behaviour this docstring described had never once been
            exercised. It was written for a deployment shape where the API and
            the worker are separate processes, which is not this harness.

            `scripts/worker.sh stop` also stops the FIXTURE SERVICE, so nothing
            can be observed during the outage either. Take any baseline before
            the stop.
            """
            run("stop")

        def restart(self) -> None:
            run("ensure")

    w = Worker()
    yield w
    # Whatever the test did, the next one needs a worker.
    w.restart()


@pytest.fixture(scope="module")
def second_worker(api_key: str):
    """A SECOND cleat-worker against the same database, for cross-worker cases.

    `cleat-worker` serves the HTTP API and runs workflows in one process, and
    this harness started exactly one -- so a class of assertions could not be
    written here at all, only described in the README's "what this suite
    structurally cannot catch". This fixture is the half of that entry that was
    fixable.

    WHAT IT MAKES EXPRESSIBLE. A concurrency key contended across PROCESSES
    rather than serialised inside one. A signal delivered to a workflow another
    worker owns. A stale-but-living run writing its outcome after a takeover --
    the shape of upstream's `test_workflow_outcome_is_owned_by_the_pending_row`,
    which cleat answers with a generation fence.

    WHAT IS SHARED, AND THAT IS THE POINT. The database, the API key and the
    fixture service. Two workers against one database IS the configuration
    under test; a second worker with its own database would prove nothing. Only
    the pid file, the log and the API port differ.

    It yields the second worker's base URL. Address it with a `Cleat` client of
    your own -- the session-scoped `cleat` fixture points at the first worker,
    and a test that wants to contend across processes needs both.

    MODULE-SCOPED, AND THAT IS NOT A STYLE CHOICE. A second worker CLAIMS
    WORK. Every workflow it picks up is one the first worker did not, so while
    it runs it changes the outcome of any test that reasons about which worker
    got what -- or how many claimed at once, or in what order.

    Session scope was the first version of this fixture and CI caught it. Once
    any test requested it the second worker ran for the remainder of the
    session, and two tests ordered after `test_cross_worker.py` failed:

        test_priority_order.py::test_priority_orders_the_second_batch
            margin 3.5, want >= 12 -- priority ordering diluted because two
            workers were claiming concurrently
        test_misfire.py::test_a_schedule_set_to_catch_up_delivers_what_it_missed
            timed out -- two schedule loops against one set of schedules

    Neither test mentions workers, neither asked for this fixture, and both
    would have been debugged as flakes. A fixture that starts a competing
    process must not outlive the module that asked for it.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    script = str(root / "scripts" / "worker.sh")
    env = {**os.environ, "CLEAT_PORTS_WORKER_INSTANCE": "2"}

    done = subprocess.run([script, "ensure"], capture_output=True, text=True, env=env)
    if done.returncode != 0:
        pytest.fail(f"second worker failed to start:\n{done.stderr[-2000:]}")

    base = os.environ["CLEAT_PORTS_API"]
    host, _, port = base.rpartition(":")
    second = f"{host}:{int(port) + 1}"

    # Assert it is actually serving before any test believes it exists. A
    # fixture that yields a URL nothing listens on turns every assertion in the
    # test into a connection error attributed to the code under test.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{second}/healthz", timeout=2) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    else:
        pytest.fail(f"second worker did not become healthy at {second}")

    yield second

    # stop-worker, NOT stop: the fixture service is shared across the whole
    # session, and `stop` takes it down with the worker.
    subprocess.run([script, "stop-worker"], capture_output=True, text=True, env=env)


@pytest.fixture(scope="session")
def holds_key_workflow(cleat: Cleat) -> str:
    return _build_and_deploy("concurrency", "holds_key")


@pytest.fixture(scope="session")
def parallel_unit_workflow(cleat: Cleat) -> str:
    """Deploy the workflow whose durable call the fixture holds open.

    Holding the WORKER SLOT is the property under test, which is why this is
    not a sleeping workflow: DurableSleepMs suspends the run instead, and fifty
    suspended runs finish in one sleep-duration on a strictly serial engine.
    """
    return _build_and_deploy("parallelunit", "parallel_unit")


@pytest.fixture(scope="session")
def plugincall_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that calls the `llm` plugin through the worker."""
    return _build_and_deploy("plugincall", "plugin_call")


@pytest.fixture(scope="session")
def pluginstream_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that calls the `llm` plugin's streaming function."""
    return _build_and_deploy("pluginstream", "plugin_stream")


@pytest.fixture(scope="session")
def poll_signal_pair(cleat: Cleat) -> tuple[str, str]:
    """Deploy the polling receiver and reuse the existing sender."""
    poller = _build_and_deploy("pollsignal", "poll_signal")
    sender = _build_and_deploy("signalsender", "signal_sender")
    return poller, sender


@pytest.fixture(scope="session")
def min_version_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that reports Version and MinVersion across a suspension."""
    return _build_and_deploy("minversion", "min_version")


@pytest.fixture(scope="session")
def dead_letter_workflow(cleat: Cleat) -> str:
    """Deploy the workflow that exhausts its retries and propagates the error."""
    return _build_and_deploy("deadletter", "dead_letter")
