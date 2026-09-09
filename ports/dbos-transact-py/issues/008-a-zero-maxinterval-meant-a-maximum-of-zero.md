## 8. A zero `MaxInterval` meant "a maximum of zero"

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#850, 2026-09-07)
**Upstream area:** `test_failures.py` — retry policy

An unset `MaxInterval` clamped every backoff to zero rather than meaning "no
maximum", so retries hammered with no delay.
