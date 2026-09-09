## 16. `PollSignal` is not replayed

**Class:** Bug · **Status:** Open (cleat-team/cleat#882)
**Upstream test:** `test_dbos.py` — `recv` without blocking
**Port test:** `test_signals.py::test_polling_finds_nothing_before_a_signal_and_finds_it_after`, skipped naming the issue

Same shape as #15, for signals. The first poll re-answers `true` after a
suspension, carrying a payload that did not exist when that line ran. A sweep of
all 50 host-call entry points found exactly these two lacking replay handling,
so the family is closed at two.
