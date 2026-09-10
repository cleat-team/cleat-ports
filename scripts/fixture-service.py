#!/usr/bin/env python3
"""A service the ports can make fail on purpose.

cleat's worker forwards any unrecognised service call to --bench-svc-url as

    POST {url}/call/{service}/{operation}

with the request JSON as the body. A 200 is the call's result; a 5xx is
classified TRANSIENT by benchSvcStatusError and so is retried under the caller's
RetryPolicy, while a 4xx other than 408/429 is PERMANENT and is not.

That classification is the whole reason this exists. Without a service that can
be told to fail a controlled number of times, a port can only observe the
permanent path -- an unresolvable service fails once and stops -- and the
retryable half of DBOS's step-retry semantics is untestable.

Protocol, one operation:

    POST /call/flaky/op   {"key": "<unique>", "fail_times": 2}
    POST /call/flaky/op   {"key": "<unique>", "fail_times": 999,
                           "fail_status": 429}

Returns `fail_status` (default 503) for the first `fail_times` calls bearing
that key, then 200 with {"attempts": n} where n counts every call including the
failures. Keys are caller-supplied and expected to be unique per test, so counts
never collide between tests or between runs.

`fail_status` exists so a test can drive cleat's classification table rather
than only the one code this fixture used to hardcode. With `fail_times` set
high, the call fails with that status on every attempt, and the call COUNT then
says which class cleat assigned: 1 means permanent, MaxAttempts means transient.

    GET /healthz          liveness, so the runner can wait rather than sleep
    GET /calls/<key>      how many times that key has been called
    GET /log/<key>        WHICH operations that key saw, in arrival order
    GET /peak/<key>       most calls ever in the handler at once, under that key
    GET /inflight/<key>   how many are in the handler RIGHT NOW
    POST /release/<key>   end every hold under that key, now

`delay_ms` holds a call inside the handler. That is what makes the worker slot
running it observably occupied, and `/peak/` is how the parallelism assertion
reads the result.

`/inflight/` and `/release/` are for a different question: not "did N run at
once" but "act on the system WHILE this one call is mid-flight". A fixed delay
cannot answer it. It gives a window of known length but says nothing about when
the call arrived, so the test is left timing its move against a duration -- a
race with a comfortable margin, and a margin is precisely what a loaded CI
runner takes away.

With these two the test waits on the observable instead:

    start the workflow
    poll GET /inflight/<key> until it reports 1     <- the call is in the handler
    do the thing under test (stop the worker, ...)  <- provably mid-segment
    POST /release/<key>                             <- let it finish

`delay_ms` remains a mandatory ceiling on the hold. A gate with no timeout turns
a forgotten release into a hung CI job, and a hang reports nothing about what it
was testing.

The ordered log exists for the saga port. A compensation test has to prove the
compensating calls happened IN REVERSE, and a counter cannot tell "withdraw
then deposit" from "deposit then withdraw" -- both are two calls. The samples-go
port asserts on the sequence, so the sequence has to be recorded.

`fail_permanently` is the saga port's other need: a step that fails ONCE and
stops. `fail_times` failures are 503/TRANSIENT and are retried, so a saga
triggered with them compensates only after the retry budget drains, and the
test would be measuring the retry policy rather than the compensation. A 400 is
PERMANENT to cleat and fails the step immediately.

Deliberately stdlib-only: the port venv installs the cleat SDK and pytest, and a
fixture that needed a web framework would make the harness depend on something
the thing under test does not.
"""

import json
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_counts = defaultdict(int)
_log = defaultdict(list)
_lock = threading.Lock()

# In-flight accounting, for asserting that cleat runs workflows CONCURRENTLY.
#
# `_peak[key]` is the largest number of /call/ requests under `key` that were
# ever inside the handler at the same moment. A serial engine produces 1; an
# engine running N workflows at once produces N, bounded by the worker's
# -concurrency (10 by default, cmd/cleat-worker/config.go).
#
# This exists so the parallelism assertion is a DIRECT measurement rather than
# a wall-clock inference. Upstream's test_max_parallel_workflows asserts 50
# workflows finish in under 30s where serial would take 250s; that shape is a
# threshold between two timings, and cleat-ports#115 is the worked example of
# it going wrong -- a ~1s cold-start landing between the hypotheses. A peak
# counter has no threshold to tune and no clock to be wrong about.
_inflight = defaultdict(int)
_peak = defaultdict(int)

# Release gates, so a held call can be ended by the TEST rather than by its own
# clock. `delay_ms` alone gives a window of known length; it does not tell the
# test when the call ARRIVED, so a test that needs the worker caught mid-segment
# still has to guess where inside the window it is. That is a race with a
# generous margin, not an assertion -- and a margin is exactly what disappears
# on a loaded CI runner.
#
# With a gate the test waits for `GET /inflight/<key>` to report the call is
# actually in the handler, acts, then `POST /release/<key>`. No margin to tune
# and nothing to be wrong about if the runner stalls: the wait is on the
# observable, not on a duration.
# A COUNTER rather than an Event, and that is not a style choice. An Event
# stays set once fired, so the second test to hold under a key it had already
# released would sail straight through the wait and the hold would silently
# stop holding -- a fixture that reports success while no longer doing the one
# thing it exists to do. The counter makes each waiter wait for a release
# NEWER than the one it arrived under, which is correct for repeat use and for
# several calls held under one key at once.
_released = defaultdict(int)
_gate = threading.Condition()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, {"ok": True})
        if self.path.startswith("/calls/"):
            key = self.path[len("/calls/"):]
            with _lock:
                return self._send(200, {"key": key, "attempts": _counts[key]})
        if self.path.startswith("/inflight/"):
            # CURRENT occupancy, as opposed to /peak/'s high-water mark. A test
            # that wants to act while a call is in flight needs to know it is in
            # flight NOW; a high-water mark of 1 is equally true a minute after
            # the call returned.
            key = self.path[len("/inflight/"):]
            with _lock:
                return self._send(200, {"key": key, "inflight": _inflight[key]})

        if self.path.startswith("/peak/"):
            key = self.path[len("/peak/"):]
            with _lock:
                return self._send(200, {
                    "key": key,
                    "peak": _peak[key],
                    "attempts": _counts[key],
                })
        if self.path.startswith("/log/"):
            key = self.path[len("/log/"):]
            with _lock:
                return self._send(200, {"key": key, "calls": list(_log[key])})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # Ollama's chat endpoint, so the llm plugin can be exercised without a
        # model or an API key. The llm plugin's ollama provider POSTs to
        # {base_url}/api/chat, and worker.sh points base_url here.
        #
        # This is the only provider of the six that takes a base_url and no
        # credential, which is what makes a hermetic plugin test possible at
        # all -- see ports/dbos-transact-py/tests/test_plugins.py.
        if self.path == "/api/chat":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                req = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid JSON body"})
            # Echo the prompt back. A canned constant would pass even if the
            # request never left the workflow, so the reply has to depend on
            # what was sent.
            messages = req.get("messages") or []
            prompt = messages[-1].get("content", "") if messages else ""

            # Streaming uses the same endpoint with "stream": true, and answers
            # NDJSON -- one JSON object per line, the last carrying done=true.
            # The reply is split into one chunk per word so the test can assert
            # that MORE THAN ONE event was recorded and that they arrive in
            # order; a single-chunk stream would pass against an implementation
            # that only ever delivers the last one.
            if req.get("stream"):
                words = f"echo:{prompt}".split(" ")
                lines = [
                    json.dumps({"message": {"role": "assistant", "content": w if i == 0 else " " + w},
                                "done": False})
                    for i, w in enumerate(words)
                ]
                lines.append(json.dumps({"message": {"content": ""}, "done": True}))
                body = ("\n".join(lines) + "\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)

            return self._send(200, {
                "model": req.get("model", ""),
                "message": {"role": "assistant", "content": f"echo:{prompt}"},
                "done": True,
                "prompt_eval_count": 1,
                "eval_count": 1,
            })

        if self.path.startswith("/release/"):
            key = self.path[len("/release/"):]
            with _lock:
                held = _inflight[key]
            with _gate:
                _released[key] += 1
                _gate.notify_all()
            return self._send(200, {"key": key, "released": held})

        if not self.path.startswith("/call/"):
            return self._send(404, {"error": "not found"})

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            # 400 is PERMANENT to cleat, which is the right answer for a body
            # it will produce identically on every retry.
            return self._send(400, {"error": "invalid JSON body"})

        key = req.get("key")
        if not key:
            return self._send(400, {"error": "key is required"})
        fail_times = int(req.get("fail_times") or 0)

        # "/call/{service}/{operation}" -> "service.operation". Recorded before
        # the failure branches, so a call that FAILS still appears in the log --
        # a saga's failing step is part of the sequence under test.
        op = ".".join(self.path[len("/call/"):].split("/")[:2])

        with _lock:
            _counts[key] += 1
            attempts = _counts[key]
            _log[key].append(op)

        if req.get("fail_permanently"):
            # 400: PERMANENT to cleat, so the step fails once instead of
            # draining a retry budget first.
            return self._send(400, {
                "error": "deliberate permanent failure",
                "key": key,
                "operation": op,
            })

        if attempts <= fail_times:
            # `fail_status` lets a caller drive cleat's whole classification
            # table, not just the two codes this fixture happened to hardcode.
            #
            # benchSvcStatusError (cmd/cleat-worker/setup.go) is:
            #
            #     4xx except 408 and 429  ->  PERMANENT, not retried
            #     408, 429, every 5xx     ->  TRANSIENT, retried per policy
            #
            # 408 and 429 are carved out of the 4xx rule, so they are the two
            # codes a refactor is most likely to get wrong -- dropping either
            # `!=` clause turns a retryable failure into a permanent one, and
            # nothing observed that until the boundary table in
            # tests/test_retries.py existed.
            #
            # Zero means 503, so every caller written before this field keeps
            # its old behaviour rather than being silently reclassified.
            return self._send(int(req.get("fail_status") or 503), {
                "error": f"deliberate failure {attempts} of {fail_times}",
                "key": key,
                "attempts": attempts,
            })

        # A caller that asks to be held here occupies the worker slot running
        # it, which is what makes concurrency observable. The sleep is
        # deliberately OUTSIDE the lock: holding _lock across it would
        # serialise the handler and the peak would read 1 however many
        # workflows the engine ran at once -- the measurement would report
        # exactly the failure it exists to detect, and look correct doing it.
        # ThreadingHTTPServer gives each request its own thread, so the only
        # thing that could serialise them is this lock.
        delay_ms = int(req.get("delay_ms") or 0)
        if delay_ms:
            # The epoch is read BEFORE the call is published as in-flight, and
            # the order is the whole correctness argument. A test releases when
            # it sees /inflight/<key> report 1, so the release can land at any
            # moment after that increment. Reading the epoch after it would let
            # a release slip into the gap, be counted, and then be waited past
            # -- the waiter would sit out the full ceiling and the test would
            # fail as a timeout with nothing to point at. Reading it first makes
            # any release after this line, however early, one this waiter is
            # still waiting for.
            with _gate:
                seen = _released[key]
            with _lock:
                _inflight[key] += 1
                if _inflight[key] > _peak[key]:
                    _peak[key] = _inflight[key]
            try:
                # A wait rather than a sleep, so `delay_ms` becomes a CEILING a
                # release can cut short instead of a duration the test must
                # outlast. Callers that pass only `delay_ms` are unaffected:
                # nothing releases, the wait runs full term, and the peak
                # measurement it was written for reads exactly as before.
                #
                # The ceiling stays mandatory on purpose. A gate with no timeout
                # turns a forgotten release into a hung CI job, and a hang is the
                # one failure that reports nothing about what it was testing.
                with _gate:
                    _gate.wait_for(lambda: _released[key] > seen,
                                   timeout=delay_ms / 1000.0)
            finally:
                with _lock:
                    _inflight[key] -= 1

        self._send(200, {"ok": True, "key": key, "attempts": attempts, "operation": op})

    def log_message(self, fmt, *args):
        sys.stderr.write("fixture: " + (fmt % args) + "\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8098
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
