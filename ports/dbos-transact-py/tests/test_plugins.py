"""Plugin calls, exercised through a real cleat-worker.

WHY THIS IS NOT A HARNESS TEST, which is the whole point of the file:

A plugin call dispatches through a registry. cleattest and the plugin harness
both register plugins DIRECTLY, in-process, so a plugin test written against
either passes whether or not a compiled worker ever populates that registry.
The gap is exactly one hop wide: a plugin registering itself via init() in a
real cleat-worker, and a deployed WASM workflow reaching it across the ABI.

So the test that means anything is one that goes through the worker, and the
same call through the harness proves nothing about it. That distinction is
narrower than "plugin calls do not work", and it is what this is written
around.

The hermetic path: of the plugins cmd/cleat-worker links, `llm` is the one that
can be driven without credentials -- ollama alone among its providers takes a
base URL and no API key, so scripts/worker.sh points ollama's base_url at the
port fixture service, which answers /api/chat. No model, no API key, no network.

(This said "llm is the only plugin cleat-worker links", which was true when
written and is being changed by cleat#891, which links 20. The reason llm is
used here is the credential-free provider, not the size of the import block, so
the sentence is phrased to survive that.)
"""

import json


def _body(final):
    body = final.get("result")
    if isinstance(body, str):
        body = json.loads(body)
    return body


def test_a_workflow_reaches_a_plugin_linked_into_the_worker(cleat, plugincall_workflow):
    """A deployed workflow's PluginCall reaches a plugin registered by init().

    The assertion is on the echoed prompt, not on a canned string: the fixture
    replies "echo:<prompt>", so a reply that matches proves the request left
    the workflow, crossed the ABI, went through the registry the worker built
    at startup, and came back. A constant would have passed on a reply the
    plugin invented.
    """
    prompt = "does the registry the worker built have anything in it"

    status, started = cleat.start(plugincall_workflow, {"prompt": prompt, "seq": 1})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the plugin call did not complete: {final.get('error') or final!r}.\n"
        "'plugin not found' here means the worker started no plugin registry -- "
        "which the harness would not have shown, because it registers plugins "
        "directly."
    )

    body = _body(final)
    assert body.get("content") == f"echo:{prompt}", (
        f"the plugin's reply did not round-trip: {body!r}"
    )


def test_a_streaming_plugin_call_delivers_every_chunk(cleat, pluginstream_workflow):
    """PluginCallStreaming is a separate host call with a separate replay path.

    It records EACH stream event in history and replays the sequence, where
    PluginCall records a single result. So the non-streaming test above says
    nothing about this one, and "records the work but never replays it" is the
    precise shape of cleat#835 and #844.

    The event count is asserted, not just the text: the fixture answers one
    chunk per word, so a count above one is what distinguishes a real stream
    from an implementation that delivers only the final chunk -- which would
    still produce entirely plausible text.
    """
    prompt = "one chunk per word"

    status, started = cleat.start(pluginstream_workflow, {"prompt": prompt, "seq": 1})
    assert status == 201, f"start rejected: {status} {started}"

    final = cleat.await_terminal(started["id"], timeout=60.0)
    assert final["status"] == "done", (
        f"the streaming plugin call did not complete: {final.get('error') or final!r}"
    )

    body = _body(final)
    assert body.get("content") == f"echo:{prompt}", (
        f"the streamed content did not reassemble: {body!r}"
    )
    assert body.get("events", 0) > 1, (
        f"only {body.get('events')} event(s) arrived, so nothing here proves the "
        f"call streamed rather than returning once: {body!r}"
    )
