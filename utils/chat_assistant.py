import os
import json
import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

_SYSTEM_PROMPT = (
    "You are an AI ESG Project Knowledge Assistant embedded in an ESG Due Diligence platform. "
    "Your role is to help users understand their project data — risks, metrics, "
    "compliance gaps, benchmarking results, regulatory requirements, reports, "
    "and pipeline execution status.\n\n"
    "STRICT RULES:\n"
    "- Answer based ONLY on the project data provided in the context below.\n"
    "- NEVER use external internet data, general AI knowledge, ChatGPT knowledge, "
    "Gemini knowledge, or any other public source.\n"
    "- If the requested information is not available in the current project data, "
    "respond clearly: 'This information is not available in the current project. "
    "Please run the relevant ESG agent or pipeline first.'\n"
    "- Do NOT make up data, speculate, or generate assumptions.\n"
    "- Be concise, accurate, and professional.\n"
    "- Use bullet points for lists.\n"
    "- Format currency values and percentages clearly.\n"
    "- Only reference data from: Registration Agent, Metric Analysis, "
    "Regulatory Tracker, Benchmarking, Risk & Opportunity Analysis, "
    "Review & Governance reports, and pipeline execution status.\n"
)


def _summarise(obj, max_len=6000):
    if obj is None:
        return None
    raw = json.dumps(obj, default=str)
    if len(raw) > max_len:
        return raw[:max_len] + "... (truncated)"
    return raw


def gather_context(session_state):
    parts = []

    ro = session_state.get("ro_results")
    if ro:
        parts.append(f"## Risk & Opportunity Analysis\n{_summarise(ro)}")

    fa = session_state.get("fa_result")
    if fa:
        parts.append(f"## Metric Analysis\n{_summarise(fa)}")

    rta = session_state.get("rta_results")
    if rta:
        parts.append(f"## Compliance Assessment\n{_summarise(rta)}")

    bm = session_state.get("bm_result")
    if bm:
        parts.append(f"## Benchmarking\n{_summarise(bm)}")

    bm_s = session_state.get("bm_summary")
    if bm_s:
        parts.append(f"## Benchmarking Summary\n{_summarise(bm_s)}")

    rv = session_state.get("review_results")
    if rv:
        parts.append(f"## Review & Governance\n{_summarise(rv)}")

    running = session_state.get("pipeline_running", False)
    completed = session_state.get("pipeline_completed", False)
    if running or completed:
        status = "Running" if running else "Completed"
        parts.append(f"## Pipeline Status: {status}")
        statuses = session_state.get("pipeline_statuses")
        if statuses:
            parts.append(f"Agent statuses: {json.dumps(statuses, default=str)}")
        errors = session_state.get("pipeline_errors")
        if errors:
            parts.append(f"Errors: {json.dumps(errors, default=str)}")

    if not parts:
        parts.append(
            "No analysis data is available yet. The user may need to "
            "run the ESG pipeline first or navigate to an analysis page."
        )

    return "\n\n".join(parts)


def get_response(user_message, chat_history, session_state):
    api_url = os.getenv("CLAUDE_API_URL", "")
    api_key = os.getenv("CLAUDE_API_KEY", "")
    model = os.getenv("CLAUDE_MODEL", "vertex_ai.anthropic.claude-opus-4-6")

    if not api_url or not api_key:
        return "AI Assistant is not configured. Please set CLAUDE_API_URL and CLAUDE_API_KEY in your .env file."

    context = gather_context(session_state)
    system_content = _SYSTEM_PROMPT + "\n\n# Project Data Context\n\n" + context

    messages = [{"role": "system", "content": system_content}]
    for msg in chat_history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.2,
    }

    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        body = resp.json()
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return content.strip() or "I received an empty response. Please try again."
    except requests.exceptions.Timeout:
        return "The request timed out. Please try again."
    except Exception as e:
        return f"Sorry, I encountered an error: {e}"
