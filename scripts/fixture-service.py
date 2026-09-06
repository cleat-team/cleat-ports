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
        self._send(404, {"error": "not found"})

    def do_POST(self):
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

        with _lock:
            _counts[key] += 1
            attempts = _counts[key]

        if attempts <= fail_times:
            # 503: TRANSIENT, so the caller's RetryPolicy applies.
            return self._send(503, {
                "error": f"deliberate failure {attempts} of {fail_times}",
                "key": key,
                "attempts": attempts,
            })

        self._send(200, {"ok": True, "key": key, "attempts": attempts})

    def log_message(self, fmt, *args):
        sys.stderr.write("fixture: " + (fmt % args) + "\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8098
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
