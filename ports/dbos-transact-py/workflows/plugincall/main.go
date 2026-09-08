// Package main is the workflow under test for plugin calls.
package main

import (
	"encoding/json"
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandlePluginCall calls the `llm` plugin's `chat` function and returns the
// content it produced.
//
// The point of this workflow is WHERE it runs, not what it computes. A plugin
// call dispatches through a registry, and both cleattest and the plugin
// harness register plugins directly -- so a plugin test written against either
// passes whether or not a real worker ever populates that registry. The gap
// this covers is exactly one hop: a plugin registering itself in a compiled
// cleat-worker via init(), and a deployed WASM workflow reaching it.
//
// `llm` is used because ollama, alone among its providers, takes a base URL and
// no credential -- so worker.sh points that base URL at the port fixture
// service, which answers /api/chat. Nothing here reaches the network. (It was
// also the only plugin cleat-worker linked when this was written; cleat#891
// changes that, which is why the reason given here is the credential, not the
// import block.)
func HandlePluginCall(h cleat.HostCalls, prompt string, seq int) (string, error) {
	_ = seq

	req := fmt.Sprintf(
		`{"provider":"ollama","model":"llama3.2","messages":[{"role":"user","content":%q}]}`,
		prompt)

	resp, err := h.PluginCall("llm", "chat", req)
	if err != nil {
		return "", fmt.Errorf("plugin call llm.chat: %w", err)
	}

	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Error string `json:"error,omitempty"`
	}
	if err := json.Unmarshal([]byte(resp), &out); err != nil {
		return "", fmt.Errorf("decoding llm.chat response %q: %w", resp, err)
	}
	if out.Error != "" {
		return "", fmt.Errorf("llm.chat reported: %s", out.Error)
	}
	if len(out.Choices) == 0 {
		return "", fmt.Errorf("llm.chat returned no choices: %s", resp)
	}

	return fmt.Sprintf(`{"content":%q}`, out.Choices[0].Message.Content), nil
}
