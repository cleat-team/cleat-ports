## `tests/test_scheduler.py` — 35 cases, read at `833794f7`

**5 portable · 6 already covered · 24 need something cleat does not have.**

Count reconciled against the inventory before classifying: 35 by `grep -cE "^(async )?def test_"`, 35 unique names, and 35 by the collection method `scripts/count-queue-cases.py` uses. No parametrize expansion in this file. (I first reported 34 — from counting a printed listing by eye rather than running `-c`. The grep never disagreed with the table; I did.)

### cleat's actual schedule surface

Established from the **store methods**, not the HTTP routes — routes are what happens to be exposed, store methods are what exists:

    ClaimDueSchedule  CreateSchedule  DeleteSchedule
    GetDueSchedules   GetDueSchedulesAcrossTenants
    ListSchedules     SetScheduleEnabled

`Schedule` carries `Name`, `DefName`, `EntryPoint`, `CronExpression`, `Input`, `Enabled`, `NextRunAt`, `LastRunAt`, `Timezone`, `MisfirePolicy`, `CatchUpLimit`, `OverlapPolicy`, `LastRunID`, `TenantID`.

**There is no get-by-name, no update, no trigger and no backfill.** Those four absences account for sixteen of the twenty-four blocked cases.

### Portable — 5 · **all five ported 2026-09-09**

| upstream case | property | ported as |
|---|---|---|
| `test_dynamic_scheduler_replace_schedule` | replacing a schedule's definition takes effect and the old one stops firing — cleat has no update, but delete+create is the same property | `test_scheduling.py::test_replacing_a_schedule_under_one_name_replaces_what_it_starts` |
| `test_long_schedule_shutdown` | a long-running scheduled workflow does not block worker shutdown | `test_scheduling.py::test_a_long_running_scheduled_workflow_does_not_hold_up_shutdown` |
| `test_backfill_with_timezone` | a cron in a named zone fires at the right wall-clock instant — cleat models `Timezone`, so this is portable without the backfill *call* | `test_schedule_timezones.py::test_a_cron_in_a_named_zone_is_scheduled_on_that_zones_clock` |
| `test_backfill_naive_datetime` | the naive/aware distinction, against cleat's `DefaultScheduleTimezone` | `test_schedule_timezones.py::test_a_schedule_that_names_no_zone_gets_the_documented_default` |
| `test_scheduled_workflow_datetime_with_portable_serializer` | a scheduled run's input survives the store unchanged | `test_scheduling.py::test_a_schedules_input_reaches_its_workflow_unchanged` |

**A sixth test was added that is not an upstream case**, and it is named here so
the count above stays honest:
`test_schedule_timezones.py::test_an_unloadable_timezone_is_refused`. It is the
control the two timezone cases need. Both of those send a zone and read a value
back, and neither can tell *honoured* from *accepted, discarded, and UTC is what
you get anyway*; a refusal can. Upstream has no equivalent because DBOS resolves
the zone in the client process, where an unloadable name raises before anything
is stored.

#### What the timezone pair does NOT assert, stated because the weaker reading is the natural one

They pin the instant cleat **computes** at creation, not the instant a workflow
starts. That is deliberate: a zone changes *when* a schedule fires and the
smallest observable difference is an hour, while `* * * * *` — the only
expression that fires soon enough to wait for — has the same next instant in
every zone on earth. So the property is unobservable by waiting and exact by
reading, and the tests are 1.6s rather than an hour.

The half they skip is already covered:
`test_a_newly_created_schedule_is_not_already_due` is the case where a computed
instant was never acted on (cleat#998, every API-created schedule firing on the
next tick regardless of its cron).

#### Falsification

Each test was run against a deliberately broken `cleat-worker` built from
`.cleat-src`, one mutation at a time, and each mutation moved only the tests it
was about:

| mutation | what went red |
|---|---|
| `handleCreateSchedule` computes `NextRunAt` in the default zone, ignoring the request | the named-zone case, `12:00Z` against a wanted `16:00Z` |
| `scheduleTimezoneOrDefault` returns `tz` unchanged | the default-zone case, reading back `''` |
| `ValidateTimezone` never consulted | the refusal case, `201` against a wanted `400` |
| the scheduler starts runs with a fixed input instead of `sch.Input` | both the replace case and the input case, each on its own `wait_until` |
| the worker ignores `SIGTERM` | the shutdown case, **5.20s** against an idle baseline of **0.29s** |

The last is the one whose instrument needed choosing rather than accepting.
`scripts/worker.sh stop` signals, waits 5s in 0.25s steps, then `SIGKILL`s — so
it **always** returns and its exit status can never fail. Only the duration
separates "exited on SIGTERM" (~0.3s) from "was killed at the cap" (~5s), and
the assertion is `< 3.0s` — below the cap on purpose, so a pass means the worker
chose to exit rather than that the harness eventually shot it.

### Already covered — 6

`test_dynamic_scheduler_fires` → `test_a_cron_schedule_actually_starts_its_workflow`.
`test_dynamic_scheduler_delete_stops_firing` → `test_deleting_a_schedule_removes_it`.
`test_dynamic_scheduler_add_after_launch` → `test_a_workflow_can_register_a_cron_schedule`.
`test_pause_resume_schedule` → `test_disabling_a_schedule_stops_it_firing` + `test_re_enabling_a_schedule_resumes_it` — cleat spells pause/resume as `enable`/`disable`.
`test_automatic_backfill_on_restart` → `test_misfire.py::test_a_schedule_set_to_catch_up_delivers_what_it_missed`; upstream calls it backfill, cleat calls it `misfire_policy: catch_up`.
`test_schedule_crud` → `test_the_schedule_policies_round_trip_through_the_api` plus the create/delete cases.

### Needs something cleat does not have — 24

**`apply_schedules` — 8.** Declarative reconciliation of a schedule *set*: `test_apply_schedules`, `_optional_context`, `_concurrent`, `_live_update`, `_preserves_runtime_state`, `test_list_schedules_undeserializable_context`, `test_client_apply_schedules`, `test_client_apply_schedules_optional_context`. cleat creates and deletes schedules one at a time and has no notion of converging a declared set.

**`trigger_schedule` — 6.** Firing a schedule on demand: `test_trigger_schedule`, `test_client_trigger_schedule`, `test_list_workflows_by_schedule_name`, `test_schedule_name_survives_export_import`, `test_static_class_method_schedule`, `test_classmethod_schedule`. The last two also need Python class-method decorator ergonomics. `test_list_workflows_by_schedule_name` additionally needs runs to be queryable by the schedule that started them — cleat records only `LastRunID`.

**Explicit `backfill_schedule` — 2.** `test_backfill_schedule`, `test_client_backfill_schedule`. Distinct from `misfire_policy: catch_up`, which is automatic and already covered: these ask for a *range* to be replayed on demand.

**A separate client API surface — 3.** `test_client_schedule_crud`, `test_client_pause_resume_schedule`, `test_client_schedule_crud_async`. `DBOSClient` is a second entry point; cleat has one HTTP API.

**Python SDK shapes — 5.** `test_schedule_crud_async` (async mirror), `test_instance_method_schedule_rejected`, `test_schedule_thread_signature` (scheduler-thread introspection), `test_schedule_crud_from_workflow` (schedule CRUD as host calls from *inside* a guest — not among cleat's exports), `test_scheduled_workflow_datetime_with_portable_serializer`'s class-registration half.

**Queues — 1.** `test_schedule_with_queue_name`, which cleat has no analogue for.

### Validation

Cases whose names announce their own answer, as a free control — all agree:

| case | the name announces | classified |
|---|---|---|
| `test_schedule_with_queue_name` | a queue | lacks it |
| `test_client_trigger_schedule` | a trigger verb, via the client | lacks both |
| `test_instance_method_schedule_rejected` | Python instance-method binding | SDK shape |
| `test_automatic_backfill_on_restart` | backfill after an outage | covered by `misfire_policy: catch_up` |
| `test_pause_resume_schedule` | pause/resume | covered by enable/disable |

Checked as a **partition**: every one of the 35 appears in exactly one bucket, none twice, none missing. `5 + 6 + 24 = 35` holds just as well with one case dropped and another double-counted.

---
