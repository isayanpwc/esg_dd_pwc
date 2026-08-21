"""
Critic pass — a second agent that challenges the first.

Self-critique in the same context tends to ratify whatever the model already
decided. This runs as a separate call with only the transcript as evidence and
one job: find conclusions the tool results do not support.

The critic is read-only by construction — it gets no tools, so it cannot alter
findings, raise requests, or write anything. It produces an assessment that
lands on the run for a human to weigh.
"""

import json
import os

from esg import clock
from esg.agentic import orchestrator, prompts
from esg.db.models import AgentRun
from esg.db.scope import require_principal
from esg.security import audit, rbac

MODEL = os.getenv("ESG_CRITIC_MODEL", "claude-opus-5")

# Deterministic checks the critic runs regardless of whether a model is
# available. Each is a property the transcript can be checked for mechanically.
_HEURISTICS = (
    ("indicative_exposure_present",
     "An exposure run used the uncalibrated judgement model. Confirm the report "
     "presents it as an indicative range, never as a single quantified amount."),
    ("illustrative_benchmarks_used",
     "A benchmark cohort with illustrative provenance was consulted. Any "
     "percentile or ranking from it is not evidence and cannot be exported."),
    ("sample_data_loaded",
     "The synthetic sample dataset was loaded. Every downstream figure in this "
     "run is illustrative and must be labelled as such."),
    ("empty_analyses",
     "One or more analyses returned no results. Confirm these are reported as "
     "data gaps rather than as clean findings."),
    ("gaps_without_requests",
     "Compliance or Scope 3 gaps were found but no information request was "
     "raised in this run. Unasked questions become unquantified risk at signing."),
)


def _mechanical_findings(steps):
    """Properties of the transcript that can be checked without a model."""
    flags = set()
    gaps_found = False
    requests_raised = False

    for step in steps:
        payload = json.loads(step.result_json) if step.result_json and step.ok else {}
        name = step.tool_name

        if name == "quantify_exposure" and payload.get("disclosure") == "indicative":
            flags.add("indicative_exposure_present")
        if name == "benchmark_metric" and payload.get("provenance") == "illustrative":
            flags.add("illustrative_benchmarks_used")
        if name == "load_canonical_sample_data" and step.ok:
            flags.add("sample_data_loaded")
        if name == "raise_information_request" and step.ok:
            requests_raised = True
        if name == "run_compliance_assessment" and payload.get("gaps", 0):
            gaps_found = True
        if name == "scope3_inventory" and payload.get("gaps"):
            gaps_found = True
        if name in ("run_greenwashing_checks",) and payload.get("count") == 0:
            flags.add("empty_analyses")
        if name == "assess_data_coverage" and payload.get("empty_tables"):
            flags.add("empty_analyses")

    if gaps_found and not requests_raised:
        flags.add("gaps_without_requests")

    return [
        {"check": key, "concern": text}
        for key, text in _HEURISTICS if key in flags
    ]


def review(session, run_id, use_model=None):
    """Critique a completed run. Returns the assessment and stores it."""
    principal = require_principal()

    run = session.get(AgentRun, run_id)
    if run is None:
        raise orchestrator.OrchestratorError("Run not found or not in scope.")
    rbac.check(rbac.RUN_ASSESSMENT, deal_id=run.deal_id, principal=principal)

    steps = orchestrator.steps_for(session, run_id)
    mechanical = _mechanical_findings(steps)

    narrative = None
    if use_model if use_model is not None else orchestrator.llm_available():
        narrative = _model_critique(session, run_id)

    assessment = {
        "run_id": run_id,
        "mechanical_checks": mechanical,
        "mechanical_count": len(mechanical),
        "narrative": narrative,
        "clean": not mechanical and not narrative,
    }
    run.critique = json.dumps(assessment, default=str)

    audit.record(
        session, principal.username, "agent.run_reviewed",
        entity_type="agent_run", entity_id=run_id, deal_id=run.deal_id,
        detail={"mechanical_findings": len(mechanical),
                "narrative": bool(narrative)},
    )
    session.flush()
    return assessment


def _model_critique(session, run_id):
    import anthropic

    payload = orchestrator.transcript(session, run_id)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=prompts.CRITIC_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{
            "role": "user",
            "content": prompts.critique_turn(
                json.dumps(payload, default=str)[:120000]
            ),
        }],
    )
    if response.stop_reason == "refusal":
        return None
    return "\n".join(b.text for b in response.content if b.type == "text").strip()
