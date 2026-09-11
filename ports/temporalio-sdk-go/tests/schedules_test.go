package tests

import (
	"fmt"
	"net/http"
	"testing"
	"time"
)

// uniqueName keeps concurrent runs of this port (the nightly matrix runs three
// dialects, and peers run the suite locally against shared databases) from
// colliding on a schedule name, which is the primary key here.
func uniqueName(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, time.Now().UnixNano())
}

// TestACreateUnderAnExistingNameIsRefusedAndTheFirstScheduleIsUntouched ports
// `TestScheduleCreateDuplicate` from temporalio/sdk-go's
// test/integration_test.go.
//
// Upstream creates a schedule, creates it again with identical options, and
// asserts the second call returns `temporal.ErrScheduleAlreadyRunning` and a
// nil handle. cleat agrees: `409 {"detail":"schedule_exists"}`.
//
// # Why this is worth a case when cleat already does the right thing
//
// Nothing in this repository asserted it. The test that sounds like it,
// `ports/dbos-transact-py/tests/test_scheduling.py::
// test_replacing_a_schedule_under_one_name_replaces_what_it_starts`, does
// DELETE-then-create and says so in its own docstring -- it asserts what a
// replacement does, never what a collision does. So the refusal was
// unasserted, and the survey that found this
// (docs/temporalio-sdk-go-schedules-survey.md) found it by reading upstream
// rather than by suspecting cleat.
//
// # The second half is the half with teeth
//
// A 409 alone would be satisfied by an implementation that refused the second
// create AFTER partially applying it. This sends a DIFFERENT def_name and cron
// on the second call and then reads the row back, so the assertion is that the
// FIRST schedule's definition survives -- which is what upstream's "the first
// run is never disturbed" property actually protects, and is the same property
// ports/durabletask-go/tests/reuse_id_test.go asserts for idempotency keys.
//
// Identical options, as upstream sends, cannot see that difference: a store
// that overwrote the row with an identical row would pass.
func TestACreateUnderAnExistingNameIsRefusedAndTheFirstScheduleIsUntouched(t *testing.T) {
	name := uniqueName("dup")
	cleanupSchedule(t, name)

	first := createSchedule(t, name, "first-def", farFutureCron, nil)
	if first.Status != http.StatusCreated && first.Status != http.StatusOK {
		t.Fatalf("the first create answered %d, want 201: %s", first.Status, first.Raw)
	}

	second := createSchedule(t, name, "second-def", "0 9 2 2 *", nil)
	if second.Status != http.StatusConflict {
		t.Fatalf("a second create under the name %q answered %d, want 409. "+
			"Upstream's policy is to refuse (ErrScheduleAlreadyRunning) and cleat's "+
			"was the same when this was written; if cleat has moved to replace-in-place, "+
			"this test is now wrong rather than cleat -- invert it and say so, because "+
			"the property that matters is the one below, not the status code: %s",
			name, second.Status, second.Raw)
	}
	if detail, _ := second.Body["detail"].(string); detail != "schedule_exists" {
		t.Errorf("the refusal carried detail %q, want \"schedule_exists\". A caller "+
			"retrying a create needs to tell this apart from a validation failure, and "+
			"the status code alone does not: %s", detail, second.Raw)
	}

	got := scheduleNamed(t, name)
	if got == nil {
		t.Fatalf("after a refused duplicate create, the schedule %q is gone from the "+
			"list entirely. The refusal deleted or replaced what it refused to replace.", name)
	}
	if got.DefName != "first-def" {
		t.Errorf("the refused create changed def_name to %q; the first schedule must be "+
			"untouched, and this is the assertion upstream's policy exists to protect. "+
			"A caller who fixed a typo by re-creating would silently be running a "+
			"different workflow.", got.DefName)
	}
	if got.Cron != farFutureCron {
		t.Errorf("the refused create changed cron_expression to %q, want %q. Same fault "+
			"as the def_name case and quieter: a schedule that still names the right "+
			"workflow on the wrong clock looks correct in a listing.", got.Cron, farFutureCron)
	}
}

// TestAnExplicitZeroCatchUpLimitReadsBackAsTheDefault ports the half of
// `TestScheduleUpdate` that is about the server rather than about the SDK.
//
// Upstream sets `CatchupWindow = 0` and asserts the server substitutes its
// 365-day default -- "update treats zero as unset", in its own comment. cleat
// does the same thing with `catch_up_limit`: send 0, read back 60.
//
// The rest of that upstream case is not portable and the survey says why: it
// drives `ScheduleUpdateOptions.DoUpdate`, a client-side read-modify-write
// callback, and cleat has no update route at all.
//
// # What this pins, and the reading it is meant to make impossible
//
// `catch_up_limit` has an obvious operator meaning -- how many missed firings
// to make up -- under which **0 means "never catch up"**. That reading is
// wrong, and nothing tells the operator so: the create answers
// `201 {"status":"created"}`, and only a list read reveals the 60.
//
// So this asserts the behaviour cleat HAS rather than the behaviour the field
// name suggests, and it is written to fail loudly if that changes, because a
// change here is a silent behaviour change for every schedule created with an
// explicit 0. If cleat later decides 0 means no-catch-up, this test is the
// thing that notices.
//
// # The control, which is the reason the omitted case is here too
//
// Sending 0 and reading 60 is only evidence of substitution if OMITTING the
// field also reads 60 -- otherwise 60 could be something the explicit 0 caused
// in some other way. And sending a non-default value must survive, or "reads
// back 60" would be consistent with a store that ignores the field entirely
// and always writes 60. Three cases, because any two of them are consistent
// with a defect the third excludes.
func TestAnExplicitZeroCatchUpLimitReadsBackAsTheDefault(t *testing.T) {
	const defaultCatchUp = 60

	t.Run("explicit zero is substituted", func(t *testing.T) {
		name := uniqueName("cu-zero")
		cleanupSchedule(t, name)
		r := createSchedule(t, name, "d", farFutureCron, map[string]any{"catch_up_limit": 0})
		if r.Status != http.StatusCreated && r.Status != http.StatusOK {
			t.Fatalf("create answered %d: %s", r.Status, r.Raw)
		}
		got := scheduleNamed(t, name)
		if got == nil {
			t.Fatalf("the schedule %q is not in the list after a 201", name)
		}
		if got.CatchUpLimit != defaultCatchUp {
			t.Errorf("catch_up_limit sent as 0 reads back as %d, want %d. cleat treats an "+
				"explicit zero as unset and substitutes the default, which is upstream's "+
				"behaviour for CatchupWindow. If this is now %d because cleat has started "+
				"honouring 0 as \"never catch up\", that is a silent behaviour change for "+
				"every schedule ever created with an explicit 0, and this test is where it "+
				"should surface.", got.CatchUpLimit, defaultCatchUp, got.CatchUpLimit)
		}
	})

	t.Run("omitting the field reads the same default", func(t *testing.T) {
		name := uniqueName("cu-omit")
		cleanupSchedule(t, name)
		r := createSchedule(t, name, "d", farFutureCron, nil)
		if r.Status != http.StatusCreated && r.Status != http.StatusOK {
			t.Fatalf("create answered %d: %s", r.Status, r.Raw)
		}
		got := scheduleNamed(t, name)
		if got == nil {
			t.Fatalf("the schedule %q is not in the list after a 201", name)
		}
		if got.CatchUpLimit != defaultCatchUp {
			t.Errorf("catch_up_limit omitted reads back as %d, want %d. This is the control "+
				"for the case above: without it, \"0 reads back 60\" would not establish that "+
				"60 is the DEFAULT.", got.CatchUpLimit, defaultCatchUp)
		}
	})

	t.Run("a non-default value survives", func(t *testing.T) {
		name := uniqueName("cu-five")
		cleanupSchedule(t, name)
		r := createSchedule(t, name, "d", farFutureCron, map[string]any{"catch_up_limit": 5})
		if r.Status != http.StatusCreated && r.Status != http.StatusOK {
			t.Fatalf("create answered %d: %s", r.Status, r.Raw)
		}
		got := scheduleNamed(t, name)
		if got == nil {
			t.Fatalf("the schedule %q is not in the list after a 201", name)
		}
		if got.CatchUpLimit != 5 {
			t.Errorf("catch_up_limit sent as 5 reads back as %d. This is the second control: "+
				"without it, the two cases above are equally consistent with a store that "+
				"ignores catch_up_limit entirely and always writes %d.",
				got.CatchUpLimit, defaultCatchUp)
		}
	})
}
