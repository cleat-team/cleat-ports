// Package main is the workflow under test for a result the store cannot hold.
//
// The entry point returns a string and the engine puts it in
// workflow_instances.result, which is JSONB on Postgres, JSON on MySQL and a
// CHECK (ISJSON(...)) column on SQL Server. So "the workflow produced a value
// the store cannot accept" is reachable from ordinary guest code, and what the
// engine does about it is what this fixture asks.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// Request names which result to return.
//
// A struct rather than a bare string: a single string parameter receives the
// ENTIRE input JSON rather than the field of that name (W003), so `kind` would
// arrive as the literal text `{"kind":"nan"}` and every case would fall to the
// default. That is not hypothetical -- it is what the first version of this
// fixture did, and every case returned the same "unknown kind" error while
// looking like it was exercising six different ones.
type Request struct {
	Kind string `json:"kind"`
}

// HandleBadResult returns the result named by the request.
//
// The values are returned as raw strings rather than marshalled, because Go's
// encoding/json refuses NaN and +Inf at the GUEST and that refusal is not the
// subject. The question is what happens when a result the guest CAN produce
// reaches a column that cannot hold it.
func HandleBadResult(h cleat.HostCalls, req Request) (string, error) {
	h.Log(fmt.Sprintf("badresult: kind=%s", req.Kind))

	switch req.Kind {
	case "valid":
		// CONTROL. Ordinary JSON, must round-trip unchanged.
		return `{"ok":true}`, nil
	case "bare-string":
		// Not JSON at all: a bare word is invalid JSON in every dialect.
		return `not json`, nil
	case "nan":
		// NaN is a JavaScript literal, not a JSON one.
		return `{"x":NaN}`, nil
	case "inf":
		return `{"x":Infinity}`, nil
	case "big-int":
		// Valid JSON, but past 2^53. A reader that decodes into a float loses
		// precision silently, so the assertion is that it survives unchanged
		// rather than merely that it survives.
		return `{"x":123456789012345678901234567890}`, nil
	case "unicode":
		// Valid JSON carrying non-ASCII, which is a different question from
		// every case above: those ask whether the store REJECTS a value, this
		// asks whether it MANGLES one it accepts. The three dialects hold the
		// result differently -- JSONB, JSON, and NVARCHAR(MAX) behind a
		// CHECK (ISJSON(...)) -- and a narrowing to VARCHAR would substitute
		// question marks while leaving status `done` and the run green.
		//
		// Deliberately mixed: a CJK pair, a combining accent, an emoji outside
		// the BMP (so a UTF-16 surrogate pair on SQL Server), and a quote to
		// keep the JSON escaping honest.
		return `{"cjk":"\u4e16\u754c","accent":"caf\u00e9","astral":"\ud83d\ude80","quoted":"say \"hi\""}`, nil
	case "empty":
		// The empty string: not valid JSON, and the value a guest returns by
		// accident more often than any of the above.
		return ``, nil
	}
	return "", fmt.Errorf("unknown kind %q", req.Kind)
}
