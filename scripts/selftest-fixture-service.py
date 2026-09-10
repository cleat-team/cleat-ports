#!/usr/bin/env python3
"""Self-test for scripts/fixture-service.py.

Every port depends on this fixture and nothing tested it. That is the wrong way
round: a fixture that quietly stops doing its job does not fail, it makes the
tests that rely on it pass for the wrong reason. A hold that stops holding turns
a concurrency assertion into a tautology, and the suite stays green.

Needs no database and no services, so it runs in seconds on a runner that is
already up -- the same argument scripts/selftest-report-path.sh makes.

WHAT IS AND IS NOT COVERED. The release path's lock ORDER -- the epoch is read
before the call is published in-flight -- is not covered here and cannot be. A
test learns the call is in flight from that very publish, so the earliest it can
release is one HTTP round trip later, and the window a wrong order would open is
a few instructions wide. Mutating the order to the wrong one leaves every case
below passing. The ordering is defended by argument, not by this file, and
saying so is the point: an uncovered line is cheaper than a case that looks like
it covers it.
"""
import json, subprocess, sys, threading, time, urllib.error, urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8231
BASE = f"http://127.0.0.1:{PORT}"
FAILS = []


def post(path, body=None, timeout=60):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def get(path, timeout=10):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read())


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def hold(key, ms, out):
    t0 = time.time()
    post("/call/svc/op", {"key": key, "delay_ms": ms})
    out.append(time.time() - t0)


def main():
    srv = subprocess.Popen([sys.executable, "scripts/fixture-service.py", str(PORT)],
                           stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            try:
                get("/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.05)
        else:
            raise SystemExit("fixture-service never became healthy")

        # A release ends a hold that would otherwise run for half a minute. The
        # ceiling is deliberately far larger than any plausible scheduling
        # hiccup, so a pass cannot be the ceiling expiring on its own.
        elapsed = []
        t = threading.Thread(target=hold, args=("st1", 30000, elapsed))
        t.start()
        inflight = 0
        for _ in range(300):
            inflight = get("/inflight/st1")["inflight"]
            if inflight:
                break
            time.sleep(0.02)
        check("/inflight reports a call that is in the handler now", inflight == 1,
              f"inflight={inflight}")
        released = post("/release/st1")
        t.join(15)
        check("a release ends a 30s hold", bool(elapsed) and elapsed[0] < 5.0,
              f"{elapsed[0]:.2f}s" if elapsed else "never returned")
        check("a release reports how many calls it found", released["released"] == 1,
              json.dumps(released))
        check("/inflight returns to zero", get("/inflight/st1")["inflight"] == 0)

        # THE REGRESSION GUARD. A one-shot Event stays set, so the next hold on
        # a key that was ever released would not hold at all -- the fixture
        # would report success while doing nothing. Written first as an Event,
        # and this case is what caught it.
        again = []
        t = threading.Thread(target=hold, args=("st1", 1500, again))
        t.start()
        t.join(15)
        check("a second hold on a released key still holds",
              bool(again) and again[0] >= 1.3,
              f"{again[0]:.2f}s, a latched gate reads ~0.00s" if again else "never returned")

        # Nothing releases, so the ceiling is the whole point: it bounds a
        # forgotten release instead of hanging CI.
        full = []
        hold("st2", 1200, full)
        check("an unreleased hold runs its full ceiling", full[0] >= 1.0, f"{full[0]:.2f}s")

        # Not a race probe -- see the module docstring. This asserts that
        # repeated hold/release cycles leave no state behind: no key's gate
        # leaks into another's, and nothing accumulates that would slow the
        # twentieth cycle relative to the first.
        worst = 0.0
        for i in range(20):
            k, e = f"st-cycle{i}", []
            t = threading.Thread(target=hold, args=(k, 20000, e))
            t.start()
            for _ in range(300):
                if get(f"/inflight/{k}")["inflight"]:
                    break
                time.sleep(0.01)
            post(f"/release/{k}")
            t.join(25)
            if not e:
                check(f"cycle {i} returned", False, "thread never finished")
                break
            worst = max(worst, e[0])
        check("20 hold/release cycles leave no state behind", worst < 5.0,
              f"worst {worst:.2f}s")

        # The behaviour every existing caller depends on, unchanged: delay_ms
        # with nobody releasing is still a plain delay, and the peak counter
        # still sees concurrent calls.
        threads = [threading.Thread(target=hold, args=("st3", 900, []))
                   for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        check("concurrent holds are still counted by /peak",
              get("/peak/st3")["peak"] == 3, json.dumps(get("/peak/st3")))
    finally:
        srv.terminate()
        srv.wait(timeout=10)

    print("\nFAILURES:", ", ".join(FAILS) if FAILS else "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
