// Package main is the workflow under test for streaming plugin calls.
package main

import (
	"fmt"
	"strings"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePluginStream calls the `llm` plugin's streaming `chat_stream` function
// and returns the concatenated content along with the number of events.
//
// Separate from plugincall because PluginCallStreaming is a separate host call
// with a separate replay path: it records EACH stream event in history and
// replays the sequence, where PluginCall records one result. A test of the
// non-streaming call says nothing about whether the streaming one records
// anything at all -- and "records the work but does not replay it" is the
// exact shape of cleat#835 and #844.
//
// Returning the event count as well as the text is deliberate. The fixture
// answers one chunk per word, so a count above one is the evidence that the
// stream was really a stream; an implementation delivering only the final
// chunk would still produce plausible text.
func HandlePluginStream(h cleat.HostCalls, prompt string, seq int) (string, error) {
	_ = seq

	req := fmt.Sprintf(
		`{"provider":"ollama","model":"llama3.2","messages":[{"role":"user","content":%q}]}`,
		prompt)

	events, err := h.PluginCallStreaming("llm", "chat_stream", req)
	if err != nil {
		return "", fmt.Errorf("plugin call llm.chat_stream: %w", err)
	}

	var content strings.Builder
	count := 0
	for ev := range events {
		content.WriteString(ev.Content)
		count++
	}

	return fmt.Sprintf(`{"content":%q,"events":%d}`, content.String(), count), nil
}
