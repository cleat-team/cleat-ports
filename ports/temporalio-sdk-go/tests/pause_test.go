package tests

import (
	"net/http"
	"testing"
)

// TestDisablingIsIdempotentAndAMissingScheduleIsRefused ports the portable half
// of `TestSchedulePause` from temporalio/sdk-go's test/integration_test.go.
//
// Upstream creates a paused schedule and then asserts, in order, that pausing
// an already-paused schedule succeeds as a no-op, that unpausing succeeds,
// that unpausing an already-unpaused one succeeds, and that pausing again
// succeeds. The note text it also asserts has no cleat counterpart — cleat's
// enable/disable carry no operator note — so what ports is the idempotence.
//
// # This case was DEFERRED, and the reason is the point of it
//
// docs/temporalio-sdk-go-schedules-survey.md recorded this as blocked rather
// than declined:
//
//	"cleat currently returns the same 200 whether the row was enabled, already
//	disabled, or ABSENT (cleat#1297) — so a test written today would pass for
//	the wrong reason, and would keep passing if the fix broke idempotence."
//
// That was exact. `DeleteSchedule` and `SetScheduleEnabled` discarded
// RowsAffected on all three dialects, so every outcome was `200 {"status":
// "disabled"}` and no assertion could separate "the row was already disabled"
// from "there is no such row". cleat#1297 landed as cleat#1302 and a missing
// name is now `404 {"detail":"schedule_not_found"}`.
//
// So this test is written as a PAIR, and neither half means anything alone:
//
//   - repeating the mutation on a schedule that EXISTS must stay 200, which is
//     upstream's asserted behaviour and the property that must not regress;
//   - the same verb on a name that does NOT exist must be 404, which is what
//     makes the 200 above evidence of idempotence rather than of a no-op.
//
// Written as one function rather than two so that a future edit cannot delete
// the discriminator and leave the idempotence assertion looking fine.
func TestDisablingIsIdempotentAndAMissingScheduleIsRefused(t *testing.T) {
	name := uniqueName("pause")
	cleanupSchedule(t, name)

	if r := createSchedule(t, name, "d", farFutureCron, nil); r.Status != http.StatusCreated && r.Status != http.StatusOK {
		t.Fatalf("create answered %d: %s", r.Status, r.Raw)
	}

	// Precondition, not decoration: if the schedule did not start enabled the
	// first disable below would be the no-op case, and the test would assert
	// idempotence while exercising nothing.
	if got := scheduleNamed(t, name); got == nil {
		t.Fatalf("the schedule %q is not in the list after a 201", name)
	} else if !got.Enabled {
		t.Fatalf("precondition: %q was created disabled, so the first disable is "+
			"already the repeat case and this test would measure nothing", name)
	}

	t.Run("the first disable changes the row", func(t *testing.T) {
		r := setScheduleEnabled(t, name, false)
		if r.Status != http.StatusOK {
			t.Fatalf("disable answered %d, want 200: %s", r.Status, r.Raw)
		}
		if got := scheduleNamed(t, name); got == nil || got.Enabled {
			t.Fatalf("after a 200 from disable, the row still reads enabled: %+v", got)
		}
	})

	t.Run("disabling an already-disabled schedule is a no-op that succeeds", func(t *testing.T) {
		r := setScheduleEnabled(t, name, false)
		if r.Status != http.StatusOK {
			t.Errorf("disabling an already-disabled schedule answered %d, want 200: %s.\n\n"+
				"This is upstream's asserted behaviour (TestSchedulePause pauses a paused "+
				"schedule and requires success) and it is the half of cleat#1297 that must "+
				"NOT change: the fix was to refuse a name that does not exist, not to refuse "+
				"a repeat. A 404 here means RowsAffected==0 is being read as not-found, which "+
				"is the MySQL trap that issue records -- a no-op UPDATE reports 0 affected "+
				"rows on MySQL and 1 on the other two dialects.", r.Status, r.Raw)
		}
		if got := scheduleNamed(t, name); got == nil || got.Enabled {
			t.Errorf("the repeated disable changed or removed the row: %+v", got)
		}
	})

	t.Run("re-enabling, and repeating that, also succeeds", func(t *testing.T) {
		if r := setScheduleEnabled(t, name, true); r.Status != http.StatusOK {
			t.Fatalf("enable answered %d, want 200: %s", r.Status, r.Raw)
		}
		if got := scheduleNamed(t, name); got == nil || !got.Enabled {
			t.Fatalf("after a 200 from enable, the row still reads disabled: %+v", got)
		}
		if r := setScheduleEnabled(t, name, true); r.Status != http.StatusOK {
			t.Errorf("enabling an already-enabled schedule answered %d, want 200: %s",
				r.Status, r.Raw)
		}
	})

	// The discriminator. Without this the three assertions above are equally
	// consistent with a handler that answers 200 to everything -- which is
	// exactly what cleat did until cleat#1302, and why this case could not be
	// written before then.
	t.Run("the same verbs on a name that does not exist are refused", func(t *testing.T) {
		missing := uniqueName("never-created")

		for _, tc := range []struct {
			what string
			do   func() response
		}{
			{"disable", func() response { return setScheduleEnabled(t, missing, false) }},
			{"enable", func() response { return setScheduleEnabled(t, missing, true) }},
			{"delete", func() response { return deleteSchedule(t, missing) }},
		} {
			// wantStatus is a variable, not a literal in the message, so the
			// message cannot disagree with the comparison. It did during this
			// test's own falsification pass: with the expectation flipped, the
			// message still read "want 404" and a grep for the new expectation
			// found nothing -- which reads exactly like an assertion that never
			// ran. A failure message that hardcodes its expectation is a
			// second, quieter copy of the thing being asserted.
			const wantStatus = http.StatusNotFound

			r := tc.do()
			if r.Status != wantStatus {
				t.Errorf("%s on the never-created name %q answered %d, want %d: %s.\n\n"+
					"A 200 here is cleat#1297 regressing: three schedule verbs answering "+
					"success for a name that does not exist. The operator consequence is "+
					"that `disable` on a mistyped name reports the schedule disabled while "+
					"it keeps firing.", tc.what, missing, r.Status, wantStatus, r.Raw)
				continue
			}
			if detail, _ := r.Body["detail"].(string); detail != "schedule_not_found" {
				t.Errorf("%s on a missing name answered 404 with detail %q, want "+
					"\"schedule_not_found\". A caller retrying needs to distinguish this "+
					"from a routing 404: %s", tc.what, detail, r.Raw)
			}
		}
	})
}
