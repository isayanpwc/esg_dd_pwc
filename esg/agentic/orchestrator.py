"""
The agent loop.

This is what makes the platform agentic rather than a page router: given a goal
and a deal, the model decides which analyses to run, in what order, reacting to
what it finds — chasing a reconciliation gap into an information request,
skipping benchmarks when the peer cohort turns out to be synthetic, loading the
sample dataset when a deal has nothing.

Two deliberate constraints:

* **The model never computes a number.** Tools do, deterministically. The model
  chooses and interprets; a figure it reports is reproducible without it.
* **Every step is persisted** to agent_run / agent_step before the next one
  runs. When a finding is challenged, the tool call that produced it is on file.

A manual loop rather than the SDK tool runner: each step has to be written to
the database inside the caller's deal scope, tool errors have to be turned into
recoverable observations rather than exceptions, and the whole run has to
degrade to the deterministic planner when no API key is configured. Owning the
loop is simpler than hooking all of that into someone else's.
"""

import json
import os
import time
import uuid

from esg import clock
from esg.agentic import prompts, tools
from esg.db.models import AgentRun, AgentStep
from esg.db.scope import require_principal
from esg.security import audit, rbac

MODEL = os.getenv("ESG_AGENT_MODEL", "claude-opus-5")
DEFAULT_MAX_STEPS = 25
MAX_RESULT_CHARS = 12000


class OrchestratorError(RuntimeError):
    pass


def llm_available():
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _client():
    import anthropic

    return anthropic.Anthropic()


def _truncate(payload):
    text = json.dumps(payload, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f'... [truncated, {len(text)} chars total]'


def _record_step(session, run, sequence, name, arguments, result, ok, error, ms):
    step = AgentStep(
        step_id=uuid.uuid4().hex[:32],
        deal_id=run.deal_id,
        run_id=run.run_id,
        sequence=sequence,
        tool_name=name,
        arguments_json=json.dumps(arguments, default=str)[:8000],
        result_json=_truncate(result) if result is not None else None,
        ok=ok,
        error=error,
        duration_ms=ms,
        started_at=clock.now(),
    )
    session.add(step)
    session.flush()
    return step


def run_goal(session, deal_id, company_id, goal, max_steps=DEFAULT_MAX_STEPS,
             planner=None):
    """Plan and execute a goal against one deal.

    `planner` forces "llm" or "deterministic"; by default the LLM planner is used
    when an API key is configured and the deterministic one otherwise.
    """
    principal = require_principal()
    rbac.check(rbac.RUN_ASSESSMENT, deal_id=deal_id, principal=principal)

    chosen = planner or ("llm" if llm_available() else "deterministic")
    run = AgentRun(
        run_id=uuid.uuid4().hex[:32],
        deal_id=deal_id,
        company_id=company_id,
        goal=goal,
        planner=chosen,
        model=MODEL if chosen == "llm" else None,
        status="Running",
        max_steps=max_steps,
        triggered_by=principal.username,
        started_at=clock.now(),
    )
    session.add(run)
    session.flush()

    audit.record(
        session, principal.username, "agent.run_started",
        entity_type="agent_run", entity_id=run.run_id, deal_id=deal_id,
        detail={"goal": goal, "planner": chosen, "model": run.model},
    )

    try:
        if chosen == "llm":
            _run_with_model(session, run, principal, company_id)
        else:
            _run_deterministic(session, run, principal, company_id)
        # Only mark success if the loop did not already set a terminal status
        # of its own (e.g. BudgetExhausted) — otherwise an exhausted run would
        # report as a clean completion.
        if run.status == "Running":
            run.status = "Completed"
    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
        run.status = "Failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = clock.now()
        audit.record(session, principal.username, "agent.run_failed",
                     entity_type="agent_run", entity_id=run.run_id,
                     deal_id=deal_id, detail={"error": run.error})
        session.flush()
        raise

    run.finished_at = clock.now()
    audit.record(
        session, principal.username, "agent.run_completed",
        entity_type="agent_run", entity_id=run.run_id, deal_id=deal_id,
        detail={"steps": run.steps_taken, "planner": run.planner},
    )
    session.flush()
    return run


# ════════════════════════════════════════════════════════════════════
#  Model-planned execution
# ════════════════════════════════════════════════════════════════════

def _run_with_model(session, run, principal, company_id):
    client = _client()
    schemas = tools.schemas()
    messages = [{
        "role": "user",
        "content": prompts.opening_turn(run.goal, run.deal_id, company_id),
    }]

    sequence = 0
    while sequence < run.max_steps:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=prompts.SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            tools=schemas,
            messages=messages,
        )

        run.input_tokens += response.usage.input_tokens or 0
        run.output_tokens += response.usage.output_tokens or 0

        if response.stop_reason == "refusal":
            run.summary = "The model declined to continue with this request."
            run.error = "refusal"
            session.flush()
            return run

        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            run.summary = "\n".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            session.flush()
            return run

        results = []
        for block in tool_uses:
            sequence += 1
            started = time.perf_counter()
            arguments = dict(block.input or {})
            try:
                payload = tools.execute(block.name, arguments, session, principal)
                ok, error = True, None
            except tools.ToolError as exc:
                payload, ok, error = {"error": str(exc)}, False, str(exc)
            except Exception as exc:  # noqa: BLE001 — surfaced to the model
                payload, ok, error = (
                    {"error": f"{type(exc).__name__}: {exc}"}, False,
                    f"{type(exc).__name__}: {exc}",
                )
            elapsed = int((time.perf_counter() - started) * 1000)

            _record_step(session, run, sequence, block.name, arguments,
                         payload, ok, error, elapsed)
            run.steps_taken = sequence

            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _truncate(payload),
                "is_error": not ok,
            })

        messages.append({"role": "user", "content": results})
        session.flush()

    run.summary = (
        f"Step budget of {run.max_steps} exhausted before the goal was concluded. "
        "The steps taken are recorded; re-run with a higher budget or a narrower goal."
    )
    run.status = "BudgetExhausted"
    session.flush()
    return run


# ════════════════════════════════════════════════════════════════════
#  Deterministic planner
# ════════════════════════════════════════════════════════════════════

def _run_deterministic(session, run, principal, company_id):
    """A fixed plan, used when no model is configured.

    Not a simulation of the agent: it is the sensible default order of work,
    with the same tools, the same scoping and the same audit trail. The product
    stays usable without an API key — it just stops adapting to what it finds.
    """
    plan = [
        ("assess_data_coverage", {"deal_id": run.deal_id, "company_id": company_id}),
        ("framework_coverage", {}),
        ("list_documents", {"deal_id": run.deal_id}),
    ]

    sequence = 0
    coverage = None
    for name, arguments in plan:
        sequence += 1
        payload, ok, error, ms = _call(name, arguments, session, principal)
        _record_step(session, run, sequence, name, arguments, payload, ok, error, ms)
        if name == "assess_data_coverage" and ok:
            coverage = payload

    # Load the bundled dataset only when the deal genuinely has nothing.
    if coverage is not None and not coverage.get("has_any_data"):
        sequence += 1
        arguments = {"deal_id": run.deal_id, "confirm_no_sources": True}
        payload, ok, error, ms = _call("load_canonical_sample_data", arguments,
                                       session, principal)
        _record_step(session, run, sequence, "load_canonical_sample_data",
                     arguments, payload, ok, error, ms)
        sequence += 1
        arguments = {"deal_id": run.deal_id, "company_id": company_id}
        coverage, ok, error, ms = _call("assess_data_coverage", arguments,
                                        session, principal)
        _record_step(session, run, sequence, "assess_data_coverage", arguments,
                     coverage, ok, error, ms)

    years = (coverage or {}).get("reporting_years") or []
    latest = max(years) if years else None

    if latest:
        for name, arguments in (
            ("run_greenwashing_checks",
             {"deal_id": run.deal_id, "company_id": company_id,
              "reporting_year": latest}),
            ("run_compliance_assessment",
             {"deal_id": run.deal_id, "company_id": company_id,
              "regulation_id": "REG001", "reporting_year": latest}),
            ("scope3_inventory",
             {"deal_id": run.deal_id, "company_id": company_id}),
            ("supplier_concentration",
             {"deal_id": run.deal_id, "company_id": company_id}),
        ):
            sequence += 1
            payload, ok, error, ms = _call(name, arguments, session, principal)
            _record_step(session, run, sequence, name, arguments, payload, ok, error, ms)

    sequence += 1
    arguments = {"deal_id": run.deal_id}
    payload, ok, error, ms = _call("list_information_requests", arguments,
                                   session, principal)
    _record_step(session, run, sequence, "list_information_requests", arguments,
                 payload, ok, error, ms)

    run.steps_taken = sequence
    run.summary = _deterministic_summary(session, run)
    session.flush()
    return run


def _call(name, arguments, session, principal):
    started = time.perf_counter()
    try:
        payload = tools.execute(name, arguments, session, principal)
        ok, error = True, None
    except tools.ToolError as exc:
        payload, ok, error = {"error": str(exc)}, False, str(exc)
    except Exception as exc:  # noqa: BLE001
        payload = {"error": f"{type(exc).__name__}: {exc}"}
        ok, error = False, f"{type(exc).__name__}: {exc}"
    return payload, ok, error, int((time.perf_counter() - started) * 1000)


def _deterministic_summary(session, run):
    steps = steps_for(session, run.run_id)
    lines = [f"Deterministic pass over {run.deal_id}: {len(steps)} steps."]
    for step in steps:
        if not step.ok:
            lines.append(f"- {step.tool_name}: failed ({step.error})")
            continue
        payload = json.loads(step.result_json) if step.result_json else {}
        if step.tool_name == "run_greenwashing_checks":
            lines.append(f"- greenwashing: {payload.get('count', 0)} finding(s) "
                         f"{payload.get('by_severity', {})}")
        elif step.tool_name == "run_compliance_assessment":
            lines.append(f"- compliance {payload.get('regulation_id')}: "
                         f"{payload.get('gaps', 0)} gap(s) of "
                         f"{payload.get('requirements_assessed', 0)} requirements")
        elif step.tool_name == "scope3_inventory":
            lines.append(f"- scope 3: {payload.get('total_tco2e')} tCO2e, "
                         f"measured share {payload.get('measured_share')}, "
                         f"{len(payload.get('gaps', []))} category gap(s)")
        elif step.tool_name == "load_canonical_sample_data":
            lines.append(f"- loaded synthetic sample data: "
                         f"{payload.get('rows_loaded', 0)} rows")
    lines.append("No LLM planner configured — this was the fixed default plan.")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
#  Reading a run back
# ════════════════════════════════════════════════════════════════════

def steps_for(session, run_id):
    from sqlalchemy import select

    return session.execute(
        select(AgentStep).where(AgentStep.run_id == run_id)
        .order_by(AgentStep.sequence)
    ).scalars().all()


def transcript(session, run_id):
    """The full reproducibility record for one run."""
    run = session.get(AgentRun, run_id)
    if run is None:
        raise OrchestratorError("Run not found or not in scope.")
    return {
        "run_id": run.run_id,
        "deal_id": run.deal_id,
        "company_id": run.company_id,
        "goal": run.goal,
        "planner": run.planner,
        "model": run.model,
        "status": run.status,
        "steps_taken": run.steps_taken,
        "tokens": {"input": run.input_tokens, "output": run.output_tokens},
        "summary": run.summary,
        "critique": run.critique,
        "error": run.error,
        "steps": [
            {"sequence": s.sequence, "tool": s.tool_name,
             "arguments": json.loads(s.arguments_json) if s.arguments_json else {},
             "ok": s.ok, "error": s.error, "duration_ms": s.duration_ms,
             "result": json.loads(s.result_json) if s.result_json and s.ok else None}
            for s in steps_for(session, run_id)
        ],
    }
