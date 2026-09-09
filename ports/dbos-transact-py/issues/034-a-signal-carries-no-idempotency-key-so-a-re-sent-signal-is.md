## 34. A signal carries no idempotency key, so a re-sent signal is a second signal

**Class:** Missing capability

**Status:** Open

**Being filed upstream by session `cleat-5c2b`, 2026-09-09.** Claimed here rather
than over a side channel: an offer that lives only in a message is invisible to
the next reader, who finds a case that looks unclaimed. If no `cleat#` reference
appears on this entry, the filing did not happen and it is free to take.

Upstream's `test_send_idempotency_key` sends with an explicit idempotency key
and asserts a duplicate send is absorbed.

`cleat_signal_workflow(target, signal, payload)` takes three arguments and no
key (`engine/imports.go:533`). Nothing else in the 52 exports carries one for
the signal path.

**cleat has idempotency, on a different operation.** Starting a run accepts an
`Idempotency-Key` header (`cmd/cleat-worker/server.go:599`) and
`test_queues.py::test_the_same_idempotency_key_starts_one_run` covers it. So the
concept exists in the engine and is absent from signals specifically — which is
the useful shape of this gap, and why it reads as an omission rather than a
design position.

**Not the same as at-least-once delivery.** A sender retrying after a timeout
cannot tell a lost signal from a slow one, and without a key the safe retry and
the duplicate are the same request. That is the practical cost.
