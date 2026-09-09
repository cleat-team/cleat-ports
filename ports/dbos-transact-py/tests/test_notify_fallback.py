"""Dispatch when the NOTIFY channel is gone.

Derived from the upstream assertions, not from upstream source. See UPSTREAM
and ../../docs/licensing.md.

Upstream's `test_notification_errors` drops the notification connection and
asserts a signal still arrives within a bound. cleat has the same two-layer
design and says so in `engine/store_notify.go`:

    NOTIFY is a best-effort hint -- the polling safety net always catches
    missed wake-ups.

Nothing exercised the second half of that sentence. Every signal test in this
suite runs with NOTIFY working, so all of them are served by the hint and none
of them can tell whether the safety net exists. That is the gap this closes.

**The seam is a flag, not a severed connection.** `cmd/cleat-worker/config.go`
declares `-notify-channel` with "(empty disables)", and `startNotifyListener`
returns a no-op when the channel is empty, leaving the dispatch loop's
nil-channel select case to block forever. So a worker started with an empty
channel is exactly a worker whose notifications never arrive -- without having
to reach past the API into the database to break a connection, which the
`samples-go` go.mod rule rules out anyway.

**Why the fixture verifies the process command line.** The failure mode here is
a false positive, and it is the whole risk of the test: if the restart silently
fails to apply the flag, NOTIFY still works, the signal arrives promptly, and
the test passes -- having asserted nothing. A green run would then be evidence
for a safety net that was never used. So the fixture reads the pidfile and
requires `-notify-channel=` on the running process before yielding, and
requires its absence again after restoring.

**What this is worth per dialect, stated plainly.** `pg_notify` is PostgreSQL
only. On MySQL and SQL Server dispatch is already poll-only, so there the flag
changes nothing and this test re-asserts a property those dialects never had
another way of satisfying. It is a real assertion on all three and a
*discriminating* one only on PostgreSQL. Running it everywhere is still right:
one path exercised everywhere beats a conditional exercised on one dialect and
assumed on the others, which is the same reasoning conftest gives for using
`deploy-workflow` on every dialect.
"""

import json
import os
import pathlib
import subprocess
import time
import uuid

import pytest

from conftest import wait_until

# The receiver's own await budget. Generous: it bounds how long the workflow is
# willing to sit there, not how quickly the signal is expected to land, and the
# assertion below is the one that measures.
AWAIT_MS = 60000

# What "within a bound" means here, derived and then measured. The dispatch
# loop sleeps `pollInterval` when idle and backs off to at most 6x that
# (`-poll` defaults to 500ms, and engine/store_interface.go documents the 6x
# ceiling), so the worst case for a poll-only worker is ~3s.
#
# Measured on PostgreSQL with NOTIFY disabled, the wake actually takes **0.22s**
# -- the awaiting row is already dispatchable when the signal lands, so the
# claim comes back on the next 500ms tick rather than after any backoff. The
# ceiling is what the bound has to clear; the measurement is what it usually
# sees.
#
# Ten is therefore ~45x the observed figure and ~3x the theoretical ceiling,
# and that slack is deliberate. This suite is shared, a flake here costs four
# sessions their signal, and the assertion's job is to separate "the polling
# fallback works" from "nothing woke it until the 60s await expired" -- a 6x
# separation at this bound. Tightening it toward the measurement would buy
# precision the claim does not need and spend reliability the suite does.
POLL_ONLY_BOUND_S = 10.0

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_WORKER_SH = _ROOT / "scripts" / "worker.sh"


def _results_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get(
        "CLEAT_PORTS_RESULTS_DIR",
        str(_ROOT / ".port-results" / os.environ.get("COMPOSE_PROJECT_NAME", "default")),
    ))


def _worker(command: str, extra_flags: str = "") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if extra_flags:
        env["CLEAT_PORTS_WORKER_EXTRA_FLAGS"] = extra_flags
    else:
        env.pop("CLEAT_PORTS_WORKER_EXTRA_FLAGS", None)
    return subprocess.run([str(_WORKER_SH), command],
                          capture_output=True, text=True, env=env)


def _worker_command_line() -> str:
    """The running worker's argv, or "" if there is no live worker.

    Read from the pidfile rather than from `pgrep cleat-worker`: several
    sessions share this checkout and a name match would find somebody else's
    process. The pidfile is per-session (ports#69).
    """
    instance = os.environ.get("CLEAT_PORTS_WORKER_INSTANCE", "1")
    name = "worker.pid" if instance == "1" else f"worker.{instance}.pid"
    pidfile = _results_dir() / name
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return ""
    out = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="],
                         capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture(scope="module")
def polling_only_worker():
    """Restart the worker with NOTIFY disabled, and put it back afterwards.

    Module-scoped: the restart costs a few seconds and every case in this file
    wants the same worker. Nothing else in the suite runs concurrently with it.
    """
    # `worker.sh stop` takes the FIXTURE SERVICE down too, and the receiver
    # announces through it -- so the restart has to complete before any test
    # body runs, which module scope gives us. Nothing is observed during the
    # gap.
    stopped = _worker("stop")
    if stopped.returncode != 0:
        pytest.fail(f"could not stop the worker:\n{stopped.stderr[-2000:]}")

    started = _worker("ensure", extra_flags="-notify-channel=")
    if started.returncode != 0:
        pytest.fail(f"could not start a poll-only worker:\n{started.stderr[-2000:]}")

    argv = _worker_command_line()
    # The check that makes a pass mean something. See the module docstring.
    assert "-notify-channel=" in argv, (
        "the worker is running WITHOUT the flag this test depends on, so "
        "NOTIFY is still delivering and a pass here would assert nothing "
        f"about the polling fallback.\n  argv: {argv or '<no live worker>'}"
    )

    try:
        yield
    finally:
        _worker("stop")
        restored = _worker("ensure")
        if restored.returncode != 0:
            pytest.fail(
                "the poll-only worker was stopped but the normal one did not "
                f"come back, so every later test will fail on connection "
                f"refused:\n{restored.stderr[-2000:]}")
        after = _worker_command_line()
        assert "-notify-channel=" not in after, (
            "the restored worker still has NOTIFY disabled, which would leave "
            f"the rest of the suite running poll-only.\n  argv: {after}")


def _body(final):
    raw = final["result"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_signal_reaches_a_worker_that_never_gets_notified(
        cleat, signal_pair, fixture_calls, polling_only_worker):
    """The polling safety net delivers what the NOTIFY hint would have."""
    receiver, _sender = signal_pair
    key = f"notify-fallback-{uuid.uuid4().hex[:8]}"

    status, started = cleat.start(receiver, {"key": key, "timeoutMs": AWAIT_MS})
    assert status == 201, f"start rejected: {status} {started}"
    run_id = started["id"]

    # The receiver announces before it awaits, so this is the point after which
    # a signal is being waited for rather than arriving early. Without it the
    # measurement below would include however long the run took to get going,
    # and a slow start would read as a slow wake-up.
    wait_until(
        lambda: fixture_calls(f"{key}-waiting") >= 1,
        timeout=60.0,
        what=f"{receiver} to reach its await",
    )

    sent_at = time.monotonic()
    status, _ = cleat.signal(run_id, "go", json.dumps({"via": "polling"}))
    assert status in (200, 202), f"signal rejected: {status}"

    final = cleat.await_terminal(run_id, timeout=90.0)
    elapsed = time.monotonic() - sent_at

    assert final["status"] == "done", f"run did not finish: {final}"
    body = _body(final)
    assert body["outcome"] == "signalled", (
        f"the await did not see the signal: {body}. `timedout` here means the "
        "polling fallback never picked it up, which is the defect this test "
        "exists to catch."
    )
    assert body["name"] == "go", f"woken by the wrong signal: {body}"

    # The bound is the second half of the upstream claim: not merely that the
    # signal arrives, but that it arrives without waiting for something slow.
    assert elapsed < POLL_ONLY_BOUND_S, (
        f"the signal took {elapsed:.1f}s to wake a poll-only worker, over the "
        f"{POLL_ONLY_BOUND_S}s bound. The dispatch loop's idle backoff tops "
        "out at 6x the 500ms poll interval, so a correct fallback lands around "
        "3s; this suggests the wake-up is waiting on something else."
    )
