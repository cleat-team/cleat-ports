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

Returns 503 for the first `fail_times` calls bearing that key, then 200 with
{"attempts": n} where n counts every call including the failures. Keys are
caller-supplied and expected to be unique per test, so counts never collide
between tests or between runs.

    GET /healthz          liveness, so the runner can wait rather than sleep
    GET /calls/<key>      how many times that key has been called
    GET /log/<key>        WHICH operations that key saw, in arrival order

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
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_counts = defaultdict(int)
_log = defaultdict(list)
_lock = threading.Lock()


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
            # 503: TRANSIENT, so the caller's RetryPolicy applies.
            return self._send(503, {
                "error": f"deliberate failure {attempts} of {fail_times}",
                "key": key,
                "attempts": attempts,
            })

        self._send(200, {"ok": True, "key": key, "attempts": attempts, "operation": op})

    def log_message(self, fmt, *args):
        sys.stderr.write("fixture: " + (fmt % args) + "\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8098
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
