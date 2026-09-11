"""One tenant cannot read another tenant's runs, through the HTTP API.

Not derived from upstream. DBOS has no tenancy model, so there is no upstream
assertion to port -- this is a cleat property the harness was, until now,
structurally unable to observe. See cleat-ports#210.

WHY THIS IS NOT COVERED BY AN ENGINE TEST. cleat has engine-level tenant tests,
including a property over definition lookup across three dialects. Those are
real coverage and this does not duplicate them. But most of the statements they
exercise carry `AND tenant_id = ?` in their own SQL, so they pass on the
application predicate whether or not row-level security works at all -- the trap
cleat's CLAUDE.md records as "a cross-tenant assertion passed against a
wide-open security policy because the store's own SQL carried tenant_id = ?".

GetWorkflowByID is the case where that cannot happen, because there is no
predicate to fall back on:

    SELECT ... FROM workflow_instances WHERE id = $1

That is the whole WHERE clause (engine/db.go). Isolation comes entirely from
beginTxWithRLS plus the policy. Measured against this harness's own database,
same statement, only the role and tenant varied:

    owner (bypasses RLS)   -> returns the row     <- what this suite used to run as
    cleat_app, tenant A    -> returns nothing
    cleat_app, tenant B    -> returns the row

So a defect here is invisible to an engine unit test and was invisible to this
suite before cleat-ports#198 and #210: #198 put the worker on a role a policy
applies to, and this file supplies the second tenant without which there are no
foreign rows for a missing predicate to return.

ON THE SHAPE OF THESE TESTS. Each asserts the KNOWN-POSITIVE before the
negative -- that B can read its own run -- and that is not ceremony. "A cannot
see B's run" is satisfied just as well by "B's run was never created", and a
seed that silently failed would leave every assertion here passing while
measuring nothing. cleat-ports#198 recorded the same hazard one layer down: an
RLS policy's USING expression is evaluated per candidate row, so a check
against an empty table returns no rows and no error whichever role you use.
"""

import json


def _leaf_under(client, name):
    """Deploy the leaf workflow under `client`'s tenant and start one run."""
    from conftest import _build

    wasm = _build("childleaf")
    code, _ = client.deploy_definition(name, wasm)
    assert code in (200, 201), f"deploying {name} answered {code}"
    code, started = client.start(name, {"ms": 1, "tag": name})
    assert code == 201, f"starting {name} answered {code}: {started}"
    return started["id"]


def test_a_tenant_cannot_read_another_tenants_run(cleat, cleat_b):
    """GET /api/workflows/{id} across the tenant boundary.

    The endpoint where RLS is the only thing standing between the two tenants.
    """
    run_a = _leaf_under(cleat, "isolation_leaf_a")
    run_b = _leaf_under(cleat_b, "isolation_leaf_b")

    assert run_a != run_b

    # KNOWN-POSITIVE FIRST. Without these two the negatives below are satisfied
    # by a seed that never landed.
    code, _ = cleat.get(run_a)
    assert code == 200, f"tenant A cannot read its OWN run: {code}"
    code, _ = cleat_b.get(run_b)
    assert code == 200, f"tenant B cannot read its OWN run: {code}"

    # The property.
    code, body = cleat.get(run_b)
    assert code == 404, (
        f"tenant A read tenant B's run {run_b}: {code} {body}. "
        "GetWorkflowByID carries no tenant predicate, so this is RLS failing "
        "open -- either the policy is not applied to this connection or the "
        "worker is running as a role that bypasses it."
    )
    code, body = cleat_b.get(run_a)
    assert code == 404, (
        f"tenant B read tenant A's run {run_a}: {code} {body}"
    )


def test_a_listing_shows_only_the_callers_own_runs(cleat, cleat_b):
    """GET /api/workflows, the other endpoint with no application predicate.

    Asserted as a DISJOINTNESS over the two listings rather than an exact set.
    An exact set would make this test a census of whatever else the suite has
    left in the database, which changes with every file added to the port --
    the "a count of a growing population is guaranteed to be wrong" failure.
    Disjointness is the actual property and it does not drift.
    """
    run_a = _leaf_under(cleat, "isolation_list_a")
    run_b = _leaf_under(cleat_b, "isolation_list_b")

    code, listing_a = cleat.api("/api/workflows")
    assert code == 200, f"listing as A answered {code}"
    code, listing_b = cleat_b.api("/api/workflows")
    assert code == 200, f"listing as B answered {code}"

    ids_a = {w["id"] for w in listing_a}
    ids_b = {w["id"] for w in listing_b}

    # KNOWN-POSITIVE: each listing contains the run its own tenant just started.
    # A pair of empty listings is disjoint, and would pass the assertion below
    # while proving nothing whatsoever.
    assert run_a in ids_a, "tenant A's listing omits the run A just started"
    assert run_b in ids_b, "tenant B's listing omits the run B just started"

    overlap = ids_a & ids_b
    assert not overlap, (
        f"{len(overlap)} run(s) appear in BOTH tenants' listings: "
        f"{sorted(overlap)[:5]}"
    )


def test_the_two_tenants_are_actually_different_tenants(cleat, cleat_b):
    """A control on the FIXTURES, which must not depend on isolation working.

    Every assertion above is vacuous if `cleat` and `cleat_b` authenticate as
    the same tenant, so something has to rule that out. The subtlety is that it
    has to rule it out WITHOUT re-testing isolation, or it cannot tell the two
    apart when both are broken at once.

    So this reads each tenant's view of its OWN run -- which needs no policy to
    work -- and compares the tenant_id the engine reports. Two ids means two
    tenants, whatever RLS is or is not doing on this connection.

    MEASURED, and it is why this test is written this way. An earlier version
    asserted `cleat.get(run_b) == 404` and carried the message "the two clients
    resolve to the same tenant". Run against a deliberately bypassing worker it
    failed with exactly that message -- against two tenants that were plainly
    different, whose ids are in the response body it printed. It named the one
    cause that was not responsible, which is the "a test whose NAME asserts the
    mechanism" failure cleat's CLAUDE.md records. As written now it PASSES under
    that same bypassing worker, which is the point: when the tests above go red
    it says whether they went red for a fixture reason or a real one.
    """
    run_a = _leaf_under(cleat, "isolation_control_a")
    run_b = _leaf_under(cleat_b, "isolation_control_b")

    code, body_a = cleat.get(run_a)
    assert code == 200, f"tenant A cannot read its own run: {code}"
    code, body_b = cleat_b.get(run_b)
    assert code == 200, f"tenant B cannot read its own run: {code}"

    assert body_a["tenant_id"] != body_b["tenant_id"], (
        "the two API keys resolve to the SAME tenant "
        f"({body_a['tenant_id']}), so every cross-tenant assertion in this "
        "file is vacuous. worker.sh refuses this at provisioning time; if it "
        "is reachable from here, the key files and tenant-b file have drifted "
        "apart from the database they name."
    )
