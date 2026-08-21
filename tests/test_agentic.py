"""The agentic layer: tool surface, scoping, the loop, and the critic.

The properties that matter are the containment ones. An agent runs with real
authority over a client's confidential data, so the tests that count are the
ones proving it cannot see past its principal, cannot exceed its role, and
cannot take the decisions that carry professional responsibility.
"""

import json

import pytest

from esg.agentic import critic, orchestrator, tools
from esg.db import repository
from esg.db.models import AgentRun, AgentStep, EsgMetricData, InformationRequest
from esg.db.scope import Principal, ScopeViolation, bind_principal
from esg.security import rbac


@pytest.fixture
def seeded(session, admin, deal_setup):
    """Two deals with metric data, so cross-deal leakage would be visible."""
    from esg.db.models import EsgMetricMaster

    with bind_principal(admin):
        session.add(EsgMetricMaster(metric_code="ENV_SCOPE1", metric_name="Scope 1",
                                    unit="tCO2e", direction="lower"))
        session.commit()
        session.add_all([
            EsgMetricData(record_id="R1", deal_id="D1", company_id="C1",
                          metric_code="ENV_SCOPE1", reporting_year=2024, value=100.0),
            EsgMetricData(record_id="R2", deal_id="D2", company_id="C2",
                          metric_code="ENV_SCOPE1", reporting_year=2024, value=999.0),
        ])
        session.commit()
    return deal_setup


# ════════════════════════════════════════════════════════════════════
#  Tool surface
# ════════════════════════════════════════════════════════════════════

def test_every_tool_declares_a_real_capability():
    known = set(rbac.ROLE_CAPABILITIES["Admin"]) | {rbac.SIGN_OFF_REPORT}
    for spec in tools.registry().values():
        assert spec.capability in known, f"{spec.name} declares unknown capability"


def test_schemas_are_well_formed_for_the_api():
    for schema in tools.schemas():
        assert schema["name"] and schema["description"]
        body = schema["input_schema"]
        assert body["type"] == "object"
        assert body["additionalProperties"] is False
        for name in body.get("required", []):
            assert name in body["properties"], f"{schema['name']}: {name} not defined"


def test_no_tool_can_take_a_human_only_decision():
    """Accepting a candidate, reviewing an exposure and signing off a report
    stay with people. The agent prepares them; it cannot execute them."""
    names = set(tools.registry())
    forbidden = {"accept_candidate", "promote_candidate", "review_exposure",
                 "sign_report", "sign_off_report", "export_report",
                 "approve_mapping", "grant_deal_access"}
    assert not (names & forbidden)

    capabilities = {t.capability for t in tools.registry().values()}
    assert rbac.SIGN_OFF_REPORT not in capabilities
    assert rbac.ACCEPT_CANDIDATE not in capabilities
    assert rbac.REVIEW_EXPOSURE not in capabilities
    assert rbac.MANAGE_ACL not in capabilities


def test_unknown_tool_is_a_recoverable_error(session, seeded):
    with bind_principal(seeded["analyst"]):
        with pytest.raises(tools.ToolError, match="No such tool"):
            tools.execute("delete_everything", {}, session, seeded["analyst"])


# ════════════════════════════════════════════════════════════════════
#  Containment
# ════════════════════════════════════════════════════════════════════

def test_tools_see_only_the_principals_deals(session, seeded):
    analyst = seeded["analyst"]  # granted D1 only
    with bind_principal(analyst):
        result = tools.execute("list_deals", {}, session, analyst)
    assert [d["deal_id"] for d in result["deals"]] == ["D1"]


def test_tool_cannot_reach_another_deal_even_when_asked(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        with pytest.raises(tools.ToolError, match="Not permitted|No access"):
            tools.execute(
                "assess_data_coverage",
                {"deal_id": "D2", "company_id": "C2"}, session, analyst,
            )


def test_data_coverage_counts_only_the_callers_deal(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        result = tools.execute(
            "assess_data_coverage",
            {"deal_id": "D1", "company_id": "C1"}, session, analyst,
        )
    assert result["row_counts"]["esg_metric_data"] == 1


def test_viewer_cannot_run_a_mutating_tool(session, seeded):
    viewer = seeded["viewer"]
    with bind_principal(viewer):
        with pytest.raises(tools.ToolError, match="Not permitted"):
            tools.execute(
                "raise_information_request",
                {"deal_id": "D1", "company_id": "C1", "title": "Anything"},
                session, viewer,
            )


def test_viewer_cannot_launch_a_run_at_all(session, seeded):
    viewer = seeded["viewer"]
    with bind_principal(viewer):
        with pytest.raises((ScopeViolation, PermissionError)):
            orchestrator.run_goal(session, "D1", "C1", "Assess the target",
                                  planner="deterministic")


# ════════════════════════════════════════════════════════════════════
#  The loop
# ════════════════════════════════════════════════════════════════════

def test_deterministic_run_records_every_step(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        run = orchestrator.run_goal(session, "D1", "C1",
                                    "Assess ESG risk for the target",
                                    planner="deterministic")
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    assert run.status == "Completed"
    assert run.planner == "deterministic"
    assert run.steps_taken == len(steps) > 0
    assert [s.sequence for s in steps] == list(range(1, len(steps) + 1))
    assert run.summary


def test_run_and_steps_are_deal_scoped(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        orchestrator.run_goal(session, "D1", "C1", "Assess", planner="deterministic")
        session.commit()

    with bind_principal(seeded["manager"]):  # granted D2 only
        assert repository.count(session, AgentRun) == 0
        assert repository.count(session, AgentStep) == 0


def test_transcript_is_the_reproducibility_record(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess",
                                    planner="deterministic")
        session.commit()
        record = orchestrator.transcript(session, run.run_id)

    assert record["goal"] == "Assess"
    assert record["planner"] == "deterministic"
    assert record["steps"]
    first = record["steps"][0]
    assert first["tool"] == "assess_data_coverage"
    assert "arguments" in first and "result" in first


def test_a_failing_tool_does_not_abort_the_run(session, seeded):
    """A tool error is an observation the plan can react to, not a crash."""
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess",
                                    planner="deterministic")
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    # REG001 is not installed in this fixture, so the compliance step fails.
    failed = [s for s in steps if not s.ok]
    assert run.status == "Completed"
    assert all(s.error for s in failed)


def test_run_is_audited(session, seeded):
    from esg.security import audit

    analyst = seeded["analyst"]
    with bind_principal(analyst):
        orchestrator.run_goal(session, "D1", "C1", "Assess", planner="deterministic")
        session.commit()
        ok, problems = audit.verify_chain(session)
    assert ok, problems


# ════════════════════════════════════════════════════════════════════
#  Critic
# ════════════════════════════════════════════════════════════════════

def test_critic_flags_gaps_that_were_never_raised(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess",
                                    planner="deterministic")
        session.commit()
        assessment = critic.review(session, run.run_id, use_model=False)
        session.commit()

    assert assessment["run_id"] == run.run_id
    checks = {c["check"] for c in assessment["mechanical_checks"]}
    # The fixture has empty tables and no IRs raised.
    assert "empty_analyses" in checks


def test_critic_is_read_only(session, seeded):
    """It gets no tools, so it cannot alter the run it is judging."""
    import inspect

    source = inspect.getsource(critic)
    assert "tools=" not in source, "critic must not pass tools to the model"

    analyst = seeded["analyst"]
    with bind_principal(analyst):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess",
                                    planner="deterministic")
        session.commit()
        before = repository.count(session, InformationRequest)
        critic.review(session, run.run_id, use_model=False)
        session.commit()
        assert repository.count(session, InformationRequest) == before


def test_critique_lands_on_the_run(session, seeded):
    analyst = seeded["analyst"]
    with bind_principal(analyst):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess",
                                    planner="deterministic")
        session.commit()
        critic.review(session, run.run_id, use_model=False)
        session.commit()
        stored = json.loads(session.get(AgentRun, run.run_id).critique)
    assert stored["run_id"] == run.run_id
