import os
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

REVIEW_SCORE_WEIGHTS = {
    "evidence_completeness": 0.30,
    "calculation_reproducibility": 0.25,
    "source_reliability": 0.20,
    "cross_agent_consistency": 0.15,
    "reviewer_verification": 0.10,
}

READINESS_THRESHOLDS = {
    "ready": 0.85,
    "qualified": 0.70,
}

FINANCIAL_IMPACT_THRESHOLD = 10_000_000

HUMAN_REVIEW_TRIGGERS = [
    "weak_evidence",
    "critical_priority",
    "high_financial_impact",
    "non_compliant_mandatory",
    "cross_agent_conflict",
    "insufficient_peers",
    "estimated_data",
    "missing_evidence",
]


def _load_csv(filename):
    try:
        path = os.path.join(UPLOAD_DIR, filename)
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_json(filename):
    import json
    try:
        path = os.path.join(BASE_DIR, "database", filename)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(filename, data):
    import json
    path = os.path.join(BASE_DIR, "database", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_available_deals():
    deals = _load_csv("deal_master.csv")
    companies = _load_csv("company_master.csv")
    if deals.empty:
        return []

    result = []
    for _, row in deals.iterrows():
        company_name = ""
        if not companies.empty:
            match = companies[companies["company_id"] == row.get("company_id")]
            if not match.empty:
                company_name = match.iloc[0].get("company_name", "")
        result.append({
            "deal_id": row.get("deal_id", ""),
            "deal_name": row.get("deal_name", ""),
            "company_id": row.get("company_id", ""),
            "company_name": company_name,
            "deal_status": row.get("deal_status", ""),
        })
    return result


def log_review_action(user, action, deal_id="", details=""):
    data = _read_json("compliance_audit_trail.json")
    entries = data.get("entries", [])
    next_id = len(entries) + 1
    entries.append({
        "id": f"AUDIT-{next_id:04d}",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "action": action,
        "framework": "Review & Governance",
        "details": details or f"Deal: {deal_id}",
        "status": "completed",
    })
    data["entries"] = entries
    _write_json("compliance_audit_trail.json", data)


# ---------------------------------------------------------------------------
# Step 1 — Access-control check
# ---------------------------------------------------------------------------

def check_access_control(deal_id, user_id):
    acl = _load_csv("deal_access_control.csv")
    users_data = _read_json("users.json")
    users_list = users_data.get("users", [])

    user_role = None
    for u in users_list:
        if u.get("username") == user_id or u.get("email") == user_id:
            user_role = u.get("role")
            break

    warnings = []
    access_records = []
    permission_level = None
    access_status = "unknown"

    if acl.empty:
        warnings.append("deal_access_control.csv not found or empty")
        if user_role == "Admin":
            access_status = "allowed"
            permission_level = "approve"
        return {
            "deal_id": deal_id,
            "user_id": user_id,
            "access_status": access_status,
            "permission_level": permission_level,
            "user_role": user_role,
            "warnings": warnings,
            "access_records": access_records,
        }

    deal_rows = acl[acl["deal_id"] == deal_id]
    if deal_rows.empty:
        warnings.append(f"No access records found for {deal_id}")

    for _, row in deal_rows.iterrows():
        revoked = not pd.isna(row.get("revoked_date", float("nan")))
        record = {
            "access_id": row.get("access_id", ""),
            "user_id": row.get("user_id", ""),
            "permission_level": row.get("permission_level", ""),
            "granted_date": str(row.get("granted_date", "")),
            "revoked_date": str(row.get("revoked_date", "")) if revoked else "",
            "status": "Revoked" if revoked else "Active",
        }
        access_records.append(record)

    user_rows = deal_rows[deal_rows["user_id"] == user_id]
    if user_rows.empty:
        if user_role == "Admin":
            access_status = "allowed"
            permission_level = "approve"
            warnings.append(
                f"No explicit ACL entry for {user_id} on {deal_id}; "
                f"Admin role grants implicit approve access"
            )
        else:
            access_status = "denied"
            warnings.append(f"User {user_id} has no access record for {deal_id}")
    else:
        active_rows = user_rows[user_rows["revoked_date"].isna()]
        if active_rows.empty:
            access_status = "denied"
            warnings.append(f"Access for {user_id} on {deal_id} has been revoked")
            revoked_row = user_rows.iloc[0]
            permission_level = revoked_row.get("permission_level", "")
        else:
            access_status = "allowed"
            best = active_rows.iloc[0]
            permission_level = best.get("permission_level", "read")

    return {
        "deal_id": deal_id,
        "user_id": user_id,
        "access_status": access_status,
        "permission_level": permission_level,
        "user_role": user_role,
        "warnings": warnings,
        "access_records": access_records,
    }


# ---------------------------------------------------------------------------
# Step 2 — Evidence validation
# ---------------------------------------------------------------------------

def validate_evidence(agent_outputs):
    issues = []
    issue_counter = 0

    def _add_issue(agent, ref, itype, severity, desc):
        nonlocal issue_counter
        issue_counter += 1
        issues.append({
            "issue_id": f"EV-{issue_counter:03d}",
            "agent_source": agent,
            "finding_ref": ref,
            "issue_type": itype,
            "severity": severity,
            "description": desc,
        })

    ro = agent_outputs.get("risk_opportunity")
    if ro and isinstance(ro, dict):
        findings = ro.get("findings", [])
        for f in findings:
            fid = f.get("finding_id", f.get("title", "Unknown"))
            priority = f.get("priority", "Medium")
            evidence_sources = f.get("evidence_sources", [])
            evidence = f.get("evidence", {})

            if not evidence_sources and not evidence.get("evidence_count"):
                sev = "Critical" if priority in ("Critical", "High") else "High"
                _add_issue(
                    "Risk & Opportunity", fid, "missing_evidence", sev,
                    f"Finding '{fid}' has no evidence sources attached.",
                )
            elif priority == "Critical" and len(evidence_sources) < 2:
                _add_issue(
                    "Risk & Opportunity", fid, "insufficient_sources", "High",
                    f"Critical finding '{fid}' has only {len(evidence_sources)} "
                    f"evidence source(s); at least 2 recommended.",
                )

            fin = f.get("financial", {})
            if fin:
                amt = fin.get("estimated_amount", 0) or 0
                method = fin.get("calculation_method", "")
                if amt > 0 and method == "not_quantifiable":
                    _add_issue(
                        "Risk & Opportunity", fid, "missing_calculation_basis", "Medium",
                        f"Finding '{fid}' has financial impact but no quantifiable "
                        f"calculation method.",
                    )

            ev_confidence = evidence.get("evidence_confidence", "")
            if ev_confidence == "Weak":
                _add_issue(
                    "Risk & Opportunity", fid, "weak_evidence", "High",
                    f"Finding '{fid}' has weak evidence confidence.",
                )

    compliance = agent_outputs.get("compliance")
    if compliance and isinstance(compliance, list):
        for reg_result in compliance:
            reg_name = reg_result.get("regulation_name", "Unknown")
            results = reg_result.get("results", [])
            for req in results:
                req_id = req.get("requirement_id", "Unknown")
                status = req.get("compliance_status", "")
                evidence_ids = req.get("evidence_document_ids", [])
                completeness = req.get("completeness_score", 0)
                severity = req.get("severity", "Medium")

                if not evidence_ids:
                    sev = "Critical" if severity == "Critical" else "High"
                    _add_issue(
                        "Compliance", f"{reg_name}/{req_id}",
                        "missing_evidence", sev,
                        f"Requirement '{req_id}' under {reg_name} has no "
                        f"evidence documents.",
                    )
                if completeness == 0 and status != "Not Applicable":
                    _add_issue(
                        "Compliance", f"{reg_name}/{req_id}",
                        "zero_completeness", "High",
                        f"Requirement '{req_id}' has 0% completeness score.",
                    )

    metrics = agent_outputs.get("metric_analysis")
    if metrics and isinstance(metrics, dict):
        metric_results = metrics.get("results", metrics.get("metrics", []))
        if isinstance(metric_results, list):
            for m in metric_results:
                code = m.get("metric_code", m.get("code", "Unknown"))
                quality = m.get("quality_flags", [])
                evidence = m.get("evidence", {})
                if isinstance(quality, list):
                    for flag in quality:
                        flag_lower = str(flag).lower()
                        if "estimated" in flag_lower:
                            _add_issue(
                                "Metric Analysis", code, "estimated_data", "Medium",
                                f"Metric '{code}' contains estimated values.",
                            )
                        if "unaudited" in flag_lower:
                            _add_issue(
                                "Metric Analysis", code, "unaudited", "Medium",
                                f"Metric '{code}' is based on unaudited data.",
                            )
                if isinstance(evidence, dict) and not evidence.get("document_id"):
                    _add_issue(
                        "Metric Analysis", code, "missing_evidence", "Medium",
                        f"Metric '{code}' has no linked evidence document.",
                    )

    benchmarking = agent_outputs.get("benchmarking")
    if benchmarking and isinstance(benchmarking, dict):
        peer_count = benchmarking.get("peer_count", 0)
        if isinstance(peer_count, (int, float)) and peer_count < 5:
            _add_issue(
                "Benchmarking", "peer_group", "insufficient_peers", "Medium",
                f"Benchmark comparison uses only {peer_count} peers; "
                f"minimum 5 recommended.",
            )

    bm_summary = agent_outputs.get("benchmarking_summary")
    if bm_summary and isinstance(bm_summary, list):
        for item in bm_summary:
            code = item.get("metric_code", "Unknown")
            pc = item.get("peer_count", 0)
            if isinstance(pc, (int, float)) and pc < 5:
                _add_issue(
                    "Benchmarking", code, "insufficient_peers", "Low",
                    f"Metric '{code}' benchmarked against only {pc} peers.",
                )

    return issues


# ---------------------------------------------------------------------------
# Step 3 — Conflict detection
# ---------------------------------------------------------------------------

def detect_conflicts(agent_outputs):
    conflicts = []
    conflict_counter = 0

    def _add_conflict(ctype, a_name, a_assess, b_name, b_assess, pillar, desc, resolution):
        nonlocal conflict_counter
        conflict_counter += 1
        conflicts.append({
            "conflict_id": f"CON-{conflict_counter:03d}",
            "conflict_type": ctype,
            "agent_a": a_name,
            "agent_a_assessment": a_assess,
            "agent_b": b_name,
            "agent_b_assessment": b_assess,
            "esg_pillar": pillar,
            "description": desc,
            "resolution_needed": resolution,
        })

    ro = agent_outputs.get("risk_opportunity")
    metrics = agent_outputs.get("metric_analysis")
    compliance = agent_outputs.get("compliance")
    benchmarking = agent_outputs.get("benchmarking")
    bm_summary = agent_outputs.get("benchmarking_summary")

    risk_pillars = {}
    if ro and isinstance(ro, dict):
        for f in ro.get("findings", []):
            if f.get("finding_type") == "Risk" and f.get("priority") in ("Critical", "High"):
                pillar = f.get("esg_pillar", "").strip()
                if pillar:
                    risk_pillars.setdefault(pillar, []).append(f)

    if metrics and isinstance(metrics, dict) and risk_pillars:
        metric_results = metrics.get("results", metrics.get("metrics", []))
        if isinstance(metric_results, list):
            for m in metric_results:
                trend = m.get("trend", m.get("trend_direction", ""))
                pillar = m.get("esg_pillar", m.get("pillar", "")).strip()
                code = m.get("metric_code", m.get("code", ""))

                if pillar in risk_pillars and isinstance(trend, str) and any(
                    kw in trend.lower() for kw in ("improving", "positive", "ahead", "on track")
                ):
                    risk_finding = risk_pillars[pillar][0]
                    _add_conflict(
                        "trend_vs_risk",
                        "Metric Analysis",
                        f"{code}: {trend}",
                        "Risk & Opportunity",
                        f"{risk_finding.get('title', '')}: {risk_finding.get('priority', '')} priority",
                        pillar,
                        f"Metric '{code}' shows a positive trend but the Risk Agent "
                        f"flags a {risk_finding.get('priority', '')} risk in the same "
                        f"'{pillar}' pillar.",
                        "Review whether the positive metric trend adequately mitigates "
                        "the identified risk, or whether they measure different aspects.",
                    )

    if ro and isinstance(ro, dict) and metrics and isinstance(metrics, dict):
        metric_results = metrics.get("results", metrics.get("metrics", []))
        if isinstance(metric_results, list):
            for m in metric_results:
                target = m.get("target_progress", m.get("on_track_flag", ""))
                code = m.get("metric_code", m.get("code", ""))
                if isinstance(target, str) and any(
                    kw in target.lower() for kw in ("on track", "ahead", "on_track")
                ):
                    for f in ro.get("findings", []):
                        if f.get("finding_type") == "Risk":
                            signals = f.get("signal_types", [])
                            if any("off" in str(s).lower() and "track" in str(s).lower() for s in signals):
                                _add_conflict(
                                    "target_vs_risk",
                                    "Metric Analysis",
                                    f"{code}: {target}",
                                    "Risk & Opportunity",
                                    f"{f.get('title', '')}: Off-track signal",
                                    f.get("esg_pillar", ""),
                                    f"Metric target for '{code}' is reported as on track but "
                                    f"the Risk Agent detected an off-track signal.",
                                    "Verify whether the target progress is based on the "
                                    "latest data and whether the risk signal is still current.",
                                )

    if compliance and isinstance(compliance, list) and bm_summary and isinstance(bm_summary, list):
        compliant_pillars = set()
        for reg_result in compliance:
            for req in reg_result.get("results", []):
                if req.get("compliance_status") == "Compliant":
                    metric = req.get("required_metric", "")
                    if metric:
                        compliant_pillars.add(metric)

        for item in bm_summary:
            code = item.get("metric_code", "")
            classification = item.get("classification", item.get("performance", ""))
            if code in compliant_pillars and isinstance(classification, str) and any(
                kw in classification.lower() for kw in ("lagging", "below", "poor")
            ):
                _add_conflict(
                    "compliance_vs_benchmark",
                    "Compliance",
                    f"{code}: Compliant",
                    "Benchmarking",
                    f"{code}: {classification}",
                    "",
                    f"Compliance assessment marks '{code}' as compliant but "
                    f"benchmarking classifies performance as '{classification}'.",
                    "Being compliant does not necessarily mean strong performance. "
                    "Review whether regulatory thresholds are adequate relative to "
                    "industry peers.",
                )

    return conflicts


# ---------------------------------------------------------------------------
# Step 4 — Review scoring
# ---------------------------------------------------------------------------

def calculate_review_scores(agent_outputs, evidence_issues, conflicts):
    ro = agent_outputs.get("risk_opportunity")

    total_findings = 0
    findings_with_evidence = 0
    findings_with_calc = 0
    verified_count = 0
    total_sources = 0

    if ro and isinstance(ro, dict):
        findings = ro.get("findings", [])
        total_findings = len(findings)
        for f in findings:
            ev = f.get("evidence", {})
            if isinstance(ev, dict):
                ec = ev.get("evidence_count", 0) or 0
                vc = ev.get("verified_count", 0) or 0
                if ec > 0:
                    findings_with_evidence += 1
                verified_count += vc
                total_sources += ec

            fin = f.get("financial", {})
            if isinstance(fin, dict):
                method = fin.get("calculation_method", "")
                if method and method != "not_quantifiable":
                    findings_with_calc += 1

    compliance = agent_outputs.get("compliance")
    if compliance and isinstance(compliance, list):
        for reg_result in compliance:
            results = reg_result.get("results", [])
            total_findings += len(results)
            for req in results:
                if req.get("evidence_document_ids"):
                    findings_with_evidence += 1

    evidence_completeness = (
        findings_with_evidence / total_findings if total_findings > 0 else 0.5
    )
    calculation_reproducibility = (
        findings_with_calc / max(total_findings, 1) if total_findings > 0 else 0.5
    )
    source_reliability = (
        verified_count / total_sources if total_sources > 0 else 0.5
    )

    conflict_penalty = len(conflicts) * 0.20
    cross_agent_consistency = max(0.0, 1.0 - conflict_penalty)

    dvh = _load_csv("data_value_history.csv")
    reviewer_verification = 1.0 if not dvh.empty else 0.5

    components = {
        "evidence_completeness": round(min(evidence_completeness, 1.0), 3),
        "calculation_reproducibility": round(min(calculation_reproducibility, 1.0), 3),
        "source_reliability": round(min(source_reliability, 1.0), 3),
        "cross_agent_consistency": round(cross_agent_consistency, 3),
        "reviewer_verification": round(reviewer_verification, 3),
    }

    overall = sum(
        components[k] * REVIEW_SCORE_WEIGHTS[k] for k in REVIEW_SCORE_WEIGHTS
    )
    overall = round(overall, 3)

    if overall >= READINESS_THRESHOLDS["ready"]:
        readiness = "Ready for report"
    elif overall >= READINESS_THRESHOLDS["qualified"]:
        readiness = "Include with qualification"
    else:
        readiness = "Human review required"

    per_finding = []
    if ro and isinstance(ro, dict):
        for f in ro.get("findings", []):
            fid = f.get("finding_id", f.get("title", ""))
            ev = f.get("evidence", {})
            ec = ev.get("evidence_count", 0) or 0 if isinstance(ev, dict) else 0
            vc = ev.get("verified_count", 0) or 0 if isinstance(ev, dict) else 0
            fin = f.get("financial", {})
            has_calc = 1.0 if isinstance(fin, dict) and fin.get("calculation_method", "") not in ("", "not_quantifiable") else 0.0
            ev_score = 1.0 if ec > 0 else 0.0
            rel_score = vc / ec if ec > 0 else 0.5
            fscore = (
                0.30 * ev_score
                + 0.25 * has_calc
                + 0.20 * rel_score
                + 0.15 * cross_agent_consistency
                + 0.10 * reviewer_verification
            )
            per_finding.append({
                "finding_id": fid,
                "score": round(fscore, 3),
                "readiness": (
                    "Ready" if fscore >= 0.85
                    else "Qualified" if fscore >= 0.70
                    else "Review required"
                ),
            })

    return {
        "overall_score": overall,
        "readiness_status": readiness,
        "component_scores": components,
        "per_finding_scores": per_finding,
        "total_findings_scored": total_findings,
    }


# ---------------------------------------------------------------------------
# Step 5 — Human-review routing
# ---------------------------------------------------------------------------

def route_human_review(agent_outputs, evidence_issues, conflicts, review_scores):
    queue = []
    item_counter = 0
    seen_refs = set()

    def _add_item(ref, agent, title, reasons, priority):
        nonlocal item_counter
        if ref in seen_refs:
            for q in queue:
                if q["finding_ref"] == ref:
                    q["trigger_reasons"] = list(set(q["trigger_reasons"] + reasons))
                    if _priority_rank(priority) > _priority_rank(q["priority"]):
                        q["priority"] = priority
            return
        seen_refs.add(ref)
        item_counter += 1
        queue.append({
            "review_item_id": f"RV-{item_counter:03d}",
            "finding_ref": ref,
            "agent_source": agent,
            "title": title,
            "trigger_reasons": reasons,
            "priority": priority,
            "status": "pending",
        })

    def _priority_rank(p):
        return {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}.get(p, 0)

    for issue in evidence_issues:
        if issue["severity"] in ("Critical", "High"):
            _add_item(
                issue["finding_ref"],
                issue["agent_source"],
                f"Evidence issue: {issue['description'][:80]}",
                [f"Evidence: {issue['issue_type']}"],
                issue["severity"],
            )

    for conflict in conflicts:
        ref = f"{conflict['agent_a']}/{conflict['agent_b']}"
        _add_item(
            ref,
            "Cross-agent",
            f"Conflict: {conflict['description'][:80]}",
            [f"Conflict: {conflict['conflict_type']}"],
            "High",
        )

    ro = agent_outputs.get("risk_opportunity")
    if ro and isinstance(ro, dict):
        for f in ro.get("findings", []):
            fid = f.get("finding_id", f.get("title", ""))
            reasons = []

            if f.get("priority") == "Critical":
                reasons.append("Critical priority finding")

            fin = f.get("financial", {})
            if isinstance(fin, dict):
                amt = fin.get("estimated_amount", 0) or 0
                if amt > FINANCIAL_IMPACT_THRESHOLD:
                    reasons.append(
                        f"Financial impact exceeds ${FINANCIAL_IMPACT_THRESHOLD:,.0f}"
                    )

            ev = f.get("evidence", {})
            if isinstance(ev, dict) and ev.get("evidence_confidence") == "Weak":
                reasons.append("Weak evidence confidence")

            if reasons:
                _add_item(
                    fid, "Risk & Opportunity", f.get("title", fid),
                    reasons,
                    "Critical" if f.get("priority") == "Critical" else "High",
                )

    compliance = agent_outputs.get("compliance")
    if compliance and isinstance(compliance, list):
        regs = _load_csv("regulation_master.csv")
        mandatory_regs = set()
        if not regs.empty:
            mandatory = regs[regs.get("mandatory_flag", pd.Series(dtype=str)).astype(str).str.upper() == "TRUE"]
            mandatory_regs = set(mandatory["regulation_id"].tolist()) if not mandatory.empty else set()

        for reg_result in compliance:
            reg_id = reg_result.get("regulation_id", "")
            reg_name = reg_result.get("regulation_name", "")
            for req in reg_result.get("results", []):
                req_id = req.get("requirement_id", "")
                status = req.get("compliance_status", "")
                if status == "Non-Compliant" and reg_id in mandatory_regs:
                    _add_item(
                        f"{reg_name}/{req_id}",
                        "Compliance",
                        f"Non-compliant with mandatory requirement {req_id}",
                        ["Non-compliant with mandatory regulation"],
                        "Critical",
                    )

    queue.sort(key=lambda x: _priority_rank(x["priority"]), reverse=True)
    return queue


# ---------------------------------------------------------------------------
# Step 6 — Final report generation
# ---------------------------------------------------------------------------

def generate_final_report(deal_id, company_id, agent_outputs,
                          access_result, evidence_issues, conflicts,
                          review_scores, review_queue):
    companies = _load_csv("company_master.csv")
    deals = _load_csv("deal_master.csv")

    company_name = ""
    if not companies.empty:
        match = companies[companies["company_id"] == company_id]
        if not match.empty:
            company_name = match.iloc[0].get("company_name", "")

    deal_name = ""
    if not deals.empty:
        match = deals[deals["deal_id"] == deal_id]
        if not match.empty:
            deal_name = match.iloc[0].get("deal_name", "")

    ro = agent_outputs.get("risk_opportunity", {})
    compliance = agent_outputs.get("compliance", [])
    metrics = agent_outputs.get("metric_analysis", {})
    benchmarking = agent_outputs.get("benchmarking", {})
    bm_summary = agent_outputs.get("benchmarking_summary", [])

    critical_findings = []
    if isinstance(ro, dict):
        for f in ro.get("findings", []):
            if f.get("priority") == "Critical":
                critical_findings.append({
                    "finding_id": f.get("finding_id", ""),
                    "title": f.get("title", ""),
                    "description": f.get("description", ""),
                    "priority": f.get("priority", ""),
                    "financial_impact": f.get("financial", {}).get("estimated_amount", 0),
                })

    compliance_gaps = []
    if isinstance(compliance, list):
        for reg_result in compliance:
            for req in reg_result.get("results", []):
                if req.get("compliance_status") in ("Non-Compliant", "Partially Compliant"):
                    compliance_gaps.append({
                        "regulation": reg_result.get("regulation_name", ""),
                        "requirement_id": req.get("requirement_id", ""),
                        "requirement_name": req.get("requirement_name", ""),
                        "status": req.get("compliance_status", ""),
                        "severity": req.get("severity", ""),
                        "gap_description": req.get("gap_description", ""),
                    })

    benchmark_performance = []
    if isinstance(bm_summary, list):
        for item in bm_summary:
            benchmark_performance.append({
                "metric_code": item.get("metric_code", ""),
                "performance": item.get("classification", item.get("performance", "")),
                "percentile": item.get("percentile", ""),
                "peer_count": item.get("peer_count", 0),
            })

    esg_trends = []
    if isinstance(metrics, dict):
        metric_results = metrics.get("results", metrics.get("metrics", []))
        if isinstance(metric_results, list):
            for m in metric_results:
                esg_trends.append({
                    "metric_code": m.get("metric_code", m.get("code", "")),
                    "trend": m.get("trend", m.get("trend_direction", "")),
                    "target_progress": m.get("target_progress", ""),
                })

    risk_register = []
    opportunities = []
    recommendations = []
    if isinstance(ro, dict):
        for f in ro.get("findings", []):
            entry = {
                "finding_id": f.get("finding_id", ""),
                "title": f.get("title", ""),
                "priority": f.get("priority", ""),
                "esg_pillar": f.get("esg_pillar", ""),
                "financial_impact": f.get("financial", {}).get("estimated_amount", 0),
            }
            if f.get("finding_type") == "Risk":
                risk_register.append(entry)
            else:
                opportunities.append(entry)
            if f.get("recommendation_category"):
                recommendations.append({
                    "finding_id": f.get("finding_id", ""),
                    "category": f.get("recommendation_category", ""),
                })

    total_findings = (
        len(ro.get("findings", [])) if isinstance(ro, dict) else 0
    )
    pending_review = sum(1 for q in review_queue if q.get("status") == "pending")

    agents_used = []
    if agent_outputs.get("metric_analysis"):
        agents_used.append("Metric Analysis")
    if agent_outputs.get("compliance"):
        agents_used.append("Compliance")
    if agent_outputs.get("benchmarking") or agent_outputs.get("benchmarking_summary"):
        agents_used.append("Benchmarking")
    if agent_outputs.get("risk_opportunity"):
        agents_used.append("Risk & Opportunity")

    narrative_parts = [
        f"This due-diligence review covers {company_name} "
        f"({'deal: ' + deal_name if deal_name else deal_id}) "
        f"using outputs from {len(agents_used)} specialist agent(s): "
        f"{', '.join(agents_used) if agents_used else 'none'}.",
    ]
    score_pct = round(review_scores["overall_score"] * 100, 1)
    narrative_parts.append(
        f"Overall quality score: {score_pct}% — "
        f"{review_scores['readiness_status']}."
    )
    if critical_findings:
        narrative_parts.append(
            f"{len(critical_findings)} critical finding(s) require immediate attention."
        )
    if compliance_gaps:
        narrative_parts.append(
            f"{len(compliance_gaps)} compliance gap(s) identified across "
            f"regulatory frameworks."
        )
    if conflicts:
        narrative_parts.append(
            f"{len(conflicts)} cross-agent conflict(s) detected and flagged "
            f"for resolution."
        )
    if pending_review:
        narrative_parts.append(
            f"{pending_review} item(s) routed for human review."
        )

    return {
        "report_id": f"RPT-{deal_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "deal_id": deal_id,
        "company_id": company_id,
        "company_name": company_name,
        "deal_name": deal_name,
        "agents_used": agents_used,
        "executive_summary": {
            "overall_quality_score": review_scores["overall_score"],
            "readiness_status": review_scores["readiness_status"],
            "total_findings": total_findings,
            "critical_findings": len(critical_findings),
            "evidence_issues_count": len(evidence_issues),
            "conflicts_count": len(conflicts),
            "human_review_items": pending_review,
            "narrative": " ".join(narrative_parts),
        },
        "access_governance": access_result,
        "evidence_validation": evidence_issues,
        "conflicts": conflicts,
        "review_scores": review_scores,
        "review_queue": review_queue,
        "sections": {
            "material_red_flags": critical_findings,
            "compliance_gaps": compliance_gaps,
            "benchmark_performance": benchmark_performance,
            "esg_trends": esg_trends,
            "risk_register": risk_register,
            "opportunities": opportunities,
            "recommendations": recommendations,
        },
        "methodology": (
            "Quality scores are computed using a weighted formula: "
            "evidence completeness (30%), calculation reproducibility (25%), "
            "source reliability (20%), cross-agent consistency (15%), and "
            "reviewer verification (10%). Findings scoring >= 85% are report-ready; "
            "70-84% are included with qualification; below 70% require human review."
        ),
        "disclaimer": (
            "This report is generated by an automated review system and should "
            "be treated as a preliminary assessment. All critical findings, "
            "financial estimates, and regulatory conclusions must be independently "
            "verified by qualified professionals before any transaction decision."
        ),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_review_governance(deal_id, company_id, user_id, agent_outputs):
    access_result = check_access_control(deal_id, user_id)
    evidence_issues = validate_evidence(agent_outputs)
    conflicts = detect_conflicts(agent_outputs)
    review_scores = calculate_review_scores(
        agent_outputs, evidence_issues, conflicts
    )
    review_queue = route_human_review(
        agent_outputs, evidence_issues, conflicts, review_scores
    )
    report = generate_final_report(
        deal_id, company_id, agent_outputs,
        access_result, evidence_issues, conflicts,
        review_scores, review_queue,
    )
    return report
