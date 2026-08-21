"""The model-planned loop, driven by a stub client.

The live API could not be exercised here (the configured key has no credit), so
the loop's own logic is pinned against a stub that returns the same shapes the
Messages API does: tool_use blocks, a final text turn, refusals, and budget
overrun. What this cannot prove is that the request parameters are accepted by
the server — that needs one live call.
"""

import json
import types

import pytest

from esg.agentic import orchestrator, tools
from esg.db import repository
from esg.db.models import AgentRun, EsgMetricData
from esg.db.scope import bind_principal


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _text(text):
    return _Block(type="text", text=text)


def _tool_use(tool_id, name, arguments):
    return _Block(type="tool_use", id=tool_id, name=name, input=arguments)


class _Response:
    def __init__(self, content, stop_reason="tool_use", usage=(10, 5)):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = types.SimpleNamespace(
            input_tokens=usage[0], output_tokens=usage[1]
        )


class StubClient:
    """Replays a scripted sequence of responses and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Snapshot messages: the loop appends to the same list across turns, so
        # storing the reference would show every call the final state.
        self.calls.append(dict(kwargs, messages=list(kwargs.get("messages", []))))
        if not self.script:
            return _Response([_text("Done.")], stop_reason="end_turn")
        return self.script.pop(0)


@pytest.fixture
def seeded(session, admin, deal_setup):
    from esg.db.models import EsgMetricMaster

    with bind_principal(admin):
        session.add(EsgMetricMaster(metric_code="ENV_SCOPE1", metric_name="S1",
                                    unit="tCO2e", direction="lower"))
        session.commit()
        session.add(EsgMetricData(record_id="R1", deal_id="D1", company_id="C1",
                                  metric_code="ENV_SCOPE1", reporting_year=2024,
                                  value=100.0))
        session.commit()
    return deal_setup


def _install(monkeypatch, client):
    monkeypatch.setattr(orchestrator, "_client", lambda: client)


def test_loop_executes_tools_and_threads_results(monkeypatch, session, seeded):
    client = StubClient([
        _Response([
            _text("Let me see what data exists."),
            _tool_use("t1", "assess_data_coverage",
                      {"deal_id": "D1", "company_id": "C1"}),
        ]),
        _Response([_text("One metric code, 2024 only. That is the finding.")],
                  stop_reason="end_turn"),
    ])
    _install(monkeypatch, client)

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    assert run.status == "Completed"
    assert run.summary.startswith("One metric code")
    assert [s.tool_name for s in steps] == ["assess_data_coverage"]
    assert steps[0].ok

    # Second request must carry assistant turn + tool_result keyed to the id.
    second = client.calls[1]["messages"]
    assert second[-1]["role"] == "user"
    result = second[-1]["content"][0]
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "t1"
    assert result["is_error"] is False


def test_request_uses_the_documented_parameters(monkeypatch, session, seeded):
    client = StubClient([_Response([_text("Nothing to do.")], stop_reason="end_turn")])
    _install(monkeypatch, client)

    with bind_principal(seeded["analyst"]):
        orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")

    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "high"}
    assert call["tools"], "tool schemas must be sent"
    # Sampling parameters are rejected on this model generation.
    assert "temperature" not in call and "top_p" not in call and "top_k" not in call


def test_tool_error_is_returned_to_the_model_not_raised(monkeypatch, session, seeded):
    """A bad argument should let the model try again, not kill the run."""
    client = StubClient([
        _Response([_tool_use("t1", "assess_data_coverage",
                             {"deal_id": "D2", "company_id": "C2"})]),  # not granted
        _Response([_tool_use("t2", "assess_data_coverage",
                             {"deal_id": "D1", "company_id": "C1"})]),
        _Response([_text("Recovered.")], stop_reason="end_turn"),
    ])
    _install(monkeypatch, client)

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    assert run.status == "Completed"
    assert [s.ok for s in steps] == [False, True]
    assert "Not permitted" in steps[0].error

    first_result = client.calls[1]["messages"][-1]["content"][0]
    assert first_result["is_error"] is True
    assert "Not permitted" in first_result["content"]


def test_parallel_tool_calls_all_return_in_one_user_turn(monkeypatch, session, seeded):
    client = StubClient([
        _Response([
            _tool_use("a", "list_deals", {}),
            _tool_use("b", "assess_data_coverage",
                      {"deal_id": "D1", "company_id": "C1"}),
        ]),
        _Response([_text("Both done.")], stop_reason="end_turn"),
    ])
    _install(monkeypatch, client)

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    assert len(steps) == 2
    results = client.calls[1]["messages"][-1]["content"]
    assert len(results) == 2, "both results must ride in a single user message"
    assert {r["tool_use_id"] for r in results} == {"a", "b"}


def test_step_budget_stops_the_loop(monkeypatch, session, seeded):
    forever = [
        _Response([_tool_use(f"t{i}", "list_deals", {})]) for i in range(20)
    ]
    _install(monkeypatch, StubClient(forever))

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess",
                                    planner="llm", max_steps=3)
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    assert run.status == "BudgetExhausted"
    assert len(steps) == 3
    assert "budget" in run.summary.lower()


def test_refusal_is_handled_not_crashed(monkeypatch, session, seeded):
    _install(monkeypatch, StubClient([_Response([], stop_reason="refusal")]))

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")
        session.commit()

    assert run.status == "Completed"
    assert run.error == "refusal"
    assert "declined" in run.summary


def test_token_usage_accumulates(monkeypatch, session, seeded):
    client = StubClient([
        _Response([_tool_use("t1", "list_deals", {})], usage=(100, 20)),
        _Response([_text("Done.")], stop_reason="end_turn", usage=(200, 30)),
    ])
    _install(monkeypatch, client)

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")
        session.commit()

    assert run.input_tokens == 300
    assert run.output_tokens == 50


def test_model_cannot_widen_its_own_scope(monkeypatch, session, seeded):
    """Even asked repeatedly, tools stay bound to the launching principal."""
    client = StubClient([
        _Response([_tool_use("t1", "assess_data_coverage",
                             {"deal_id": "D2", "company_id": "C2"})]),
        _Response([_tool_use("t2", "list_deals", {})]),
        _Response([_text("Only D1 visible.")], stop_reason="end_turn"),
    ])
    _install(monkeypatch, client)

    with bind_principal(seeded["analyst"]):
        run = orchestrator.run_goal(session, "D1", "C1", "Assess", planner="llm")
        session.commit()
        steps = orchestrator.steps_for(session, run.run_id)

    assert steps[0].ok is False
    visible = json.loads(steps[1].result_json)
    assert [d["deal_id"] for d in visible["deals"]] == ["D1"]


def test_large_tool_results_are_truncated_before_being_sent(monkeypatch, session, seeded):
    payload = {"blob": "x" * (orchestrator.MAX_RESULT_CHARS + 5000)}
    text = orchestrator._truncate(payload)
    assert len(text) < len(json.dumps(payload))
    assert "truncated" in text
