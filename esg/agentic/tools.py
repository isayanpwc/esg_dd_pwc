"""
The tool surface the orchestrator plans over.

The architecture this implements is **agentic orchestration over deterministic
computation**: the model decides *what to look at and in what order*; it never
decides *what a number is*. Every tool here is a thin wrapper over the existing
deterministic modules, so a figure the agent surfaces is the same figure a human
clicking the same button would get, and it is reproducible months later.

Three properties hold for every tool, and they are enforced here rather than
trusted to the prompt:

* **Scoped.** Handlers receive the caller's Principal and run inside it, so
  esg.db.scope filters every read and rejects every out-of-deal write. An agent
  cannot see further than the analyst who launched it.
* **Capability-checked.** Each tool declares the rbac capability it needs; the
  check runs before the handler, so an agent launched by a Viewer cannot ingest.
* **Gated.** No tool promotes a metric candidate, signs off a report, or marks
  an exposure reviewed. Those stay human decisions — the agent can only prepare
  and recommend them.
"""

import json
from dataclasses import dataclass, field

from esg.security import rbac


class ToolError(RuntimeError):
    """Recoverable — returned to the model as a tool_result with is_error."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: object
    capability: str
    mutates: bool = False
    deal_arg: str = "deal_id"

    def anthropic_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


_REGISTRY = {}


def tool(name, description, schema, capability, mutates=False, deal_arg="deal_id"):
    def register(fn):
        _REGISTRY[name] = Tool(
            name=name, description=description, input_schema=schema,
            handler=fn, capability=capability, mutates=mutates, deal_arg=deal_arg,
        )
        return fn

    return register


def registry():
    return dict(_REGISTRY)


def schemas():
    return [t.anthropic_schema() for t in _REGISTRY.values()]


def execute(name, arguments, session, principal):
    """Run one tool under the caller's authority.

    Returns a JSON-serialisable dict. Raises ToolError for anything the model
    could plausibly recover from by choosing different arguments.
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ToolError(f"No such tool {name!r}. Available: {', '.join(sorted(_REGISTRY))}")

    deal_id = arguments.get(spec.deal_arg) if spec.deal_arg else None
    try:
        rbac.check(spec.capability, deal_id=deal_id, principal=principal)
    except PermissionError as exc:
        raise ToolError(f"Not permitted: {exc}") from exc

    try:
        return spec.handler(session=session, principal=principal, **arguments)
    except ToolError:
        raise
    except PermissionError as exc:
        raise ToolError(f"Not permitted: {exc}") from exc
    except TypeError as exc:
        raise ToolError(f"Bad arguments for {name}: {exc}") from exc


def _obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_DEAL = {"deal_id": {"type": "string", "description": "Deal identifier, e.g. DEAL001"}}
_COMPANY = {"company_id": {"type": "string", "description": "Target company identifier"}}


# ════════════════════════════════════════════════════════════════════
#  Orientation
# ════════════════════════════════════════════════════════════════════

@tool(
    name="list_deals",
    description=(
        "List the deals the caller has access to, with the target company and "
        "status. Call this first when no deal has been named, to find out what "
        "can be worked on. Returns only deals the caller is granted."
    ),
    schema=_obj({}),
    capability=rbac.VIEW_DEAL,
    deal_arg=None,
)
def _list_deals(session, principal, **_):
    from esg.db import repository
    from esg.db.models import CompanyMaster, DealMaster

    deals = repository.fetch_all(session, DealMaster)
    out = []
    for deal in deals:
        company = session.get(CompanyMaster, deal.company_id)
        out.append({
            "deal_id": deal.deal_id,
            "deal_name": deal.deal_name,
            "company_id": deal.company_id,
            "company_name": company.company_name if company else None,
            "industry": company.industry if company else None,
            "country": company.country if company else None,
            "status": deal.deal_status,
        })
    return {"deals": out, "count": len(out)}


@tool(
    name="assess_data_coverage",
    description=(
        "Report what data actually exists for a deal: how many rows in each "
        "canonical table, which metrics and years are covered, how many "
        "documents are ingested, and which expected tables are empty. Call this "
        "early — it tells you which analyses are possible and which would be "
        "based on nothing."
    ),
    schema=_obj({**_DEAL, **_COMPANY}, required=["deal_id", "company_id"]),
    capability=rbac.VIEW_DEAL,
)
def _assess_data_coverage(session, principal, deal_id, company_id, **_):
    from esg.db import repository
    from esg.db.models import (
        Certification, ComplianceAssessment, ControversyRecord, EsgDocumentRegister,
        EsgMetricData, EsgTarget, LegalPenalty, SupplierEsgAssessment,
    )

    counts = {}
    for model in (EsgMetricData, EsgDocumentRegister, ComplianceAssessment,
                  ControversyRecord, LegalPenalty, EsgTarget, Certification,
                  SupplierEsgAssessment):
        counts[model.__tablename__] = repository.count(session, model)

    metrics = repository.fetch_all(
        session, EsgMetricData, EsgMetricData.company_id == company_id
    )
    years = sorted({m.reporting_year for m in metrics if m.reporting_year})
    codes = sorted({m.metric_code for m in metrics if m.metric_code})

    empty = [name for name, n in counts.items() if n == 0]
    return {
        "deal_id": deal_id,
        "company_id": company_id,
        "row_counts": counts,
        "metric_codes": codes,
        "metric_code_count": len(codes),
        "reporting_years": years,
        "empty_tables": empty,
        "has_any_data": any(counts.values()),
        "note": (
            "Tables listed in empty_tables have no rows for this deal. Analyses "
            "that depend on them will return nothing — treat that as a data gap "
            "to raise, not as a clean result."
        ),
    }


@tool(
    name="load_canonical_sample_data",
    description=(
        "Load the bundled canonical dataset for a deal when no data source has "
        "been registered. Use ONLY when assess_data_coverage shows no data — it "
        "is synthetic sample data for demonstration, never real engagement data, "
        "and everything derived from it must be labelled as such. Returns what "
        "was loaded and what was quarantined."
    ),
    schema=_obj({**_DEAL, "confirm_no_sources": {
        "type": "boolean",
        "description": "Must be true; confirms you checked coverage first and found none.",
    }}, required=["deal_id", "confirm_no_sources"]),
    capability=rbac.INGEST_DATA,
    mutates=True,
)
def _load_canonical_sample_data(session, principal, deal_id, confirm_no_sources, **_):
    from esg.etl import seed

    if not confirm_no_sources:
        raise ToolError(
            "Refusing to load sample data without confirm_no_sources=true. "
            "Call assess_data_coverage first."
        )
    if seed.has_registered_sources(session, deal_id):
        raise ToolError(
            "This deal already has registered data. Loading sample data over real "
            "engagement data is refused — analyse what is there instead."
        )
    return seed.load_canonical_dataset(session, deal_id=deal_id)


# ════════════════════════════════════════════════════════════════════
#  Documents
# ════════════════════════════════════════════════════════════════════

@tool(
    name="list_documents",
    description=(
        "List ingested documents for a deal with their processing status and "
        "page counts. Use to find evidence sources, and to spot documents that "
        "need OCR or failed processing."
    ),
    schema=_obj(_DEAL, required=["deal_id"]),
    capability=rbac.VIEW_DEAL,
)
def _list_documents(session, principal, deal_id, **_):
    from esg.db import repository
    from esg.db.models import EsgDocumentRegister

    docs = repository.fetch_all(session, EsgDocumentRegister)
    return {"documents": [
        {"document_id": d.document_id, "name": d.document_name,
         "type": d.document_type, "year": d.reporting_year,
         "pages": d.page_count, "status": d.processing_status,
         "error": d.processing_error}
        for d in docs
    ], "count": len(docs)}


@tool(
    name="extract_metrics_from_document",
    description=(
        "Run metric extraction over an ingested document. Produces CANDIDATES "
        "with page citations — it does not add anything to the analysis tables. "
        "A human must accept each candidate separately. Returns what was found "
        "with confidence scores."
    ),
    schema=_obj({**_DEAL, "document_id": {"type": "string"}},
                required=["deal_id", "document_id"]),
    capability=rbac.INGEST_DATA,
    mutates=True,
)
def _extract_metrics(session, principal, deal_id, document_id, **_):
    from esg.documents import extract

    created = extract.extract_document(session, document_id)
    return {
        "document_id": document_id,
        "candidates_created": len(created),
        "candidates": [
            {"candidate_id": c.candidate_id, "metric_code": c.metric_code,
             "value": c.value, "unit": c.unit, "year": c.reporting_year,
             "page": c.page_number, "confidence": c.confidence,
             "snippet": (c.snippet or "")[:160]}
            for c in created[:40]
        ],
        "note": "Candidates are pending human review; none are in esg_metric_data yet.",
    }


@tool(
    name="list_pending_candidates",
    description=(
        "List extracted metric candidates awaiting human review for a deal. Use "
        "to report how much evidence is queued for an analyst, and to identify "
        "low-confidence readings worth flagging."
    ),
    schema=_obj({**_DEAL, "min_confidence": {"type": "number"}},
                required=["deal_id"]),
    capability=rbac.VIEW_DEAL,
)
def _list_candidates(session, principal, deal_id, min_confidence=None, **_):
    from esg.documents import extract

    pending = extract.pending_candidates(
        session, deal_id=deal_id, min_confidence=min_confidence
    )
    return {"pending": len(pending), "candidates": [
        {"candidate_id": c.candidate_id, "metric_code": c.metric_code,
         "value": c.value, "unit": c.unit, "year": c.reporting_year,
         "page": c.page_number, "confidence": c.confidence}
        for c in pending[:50]
    ]}


# ════════════════════════════════════════════════════════════════════
#  Analysis
# ════════════════════════════════════════════════════════════════════

@tool(
    name="run_compliance_assessment",
    description=(
        "Assess a company against a regulation's requirements as they stood in "
        "the reporting year, and return the gaps. Uses the effective-dated "
        "ruleset, so an older period is scored against the rules that actually "
        "applied. Returns per-requirement status plus the resolved ruleset "
        "version."
    ),
    schema=_obj({
        **_DEAL, **_COMPANY,
        "regulation_id": {"type": "string", "description": "e.g. REG001 for BRSR"},
        "reporting_year": {"type": "integer"},
    }, required=["deal_id", "company_id", "regulation_id", "reporting_year"]),
    capability=rbac.RUN_ASSESSMENT,
)
def _run_compliance(session, principal, deal_id, company_id, regulation_id,
                    reporting_year, **_):
    from datetime import date

    from esg.db import repository
    from esg.db.models import EsgMetricData
    from esg.frameworks import registry

    as_of = date(reporting_year, 12, 31)
    try:
        version = registry.resolve_ruleset_version(session, regulation_id, as_of)
    except registry.FrameworkError as exc:
        raise ToolError(str(exc)) from exc

    requirements = registry.requirements_in_force(session, regulation_id, as_of)
    have = {
        m.metric_code for m in repository.fetch_all(
            session, EsgMetricData,
            EsgMetricData.company_id == company_id,
            EsgMetricData.reporting_year == reporting_year,
        )
    }

    results = []
    for req in requirements:
        needed = req.required_metric_code
        if not needed:
            status = "Manual review"
        elif needed in have:
            status = "Evidenced"
        else:
            status = "Gap"
        results.append({
            "requirement_id": req.requirement_id,
            "code": req.requirement_code,
            "name": req.requirement_name,
            "required_metric": needed,
            "status": status,
            "mandatory": req.mandatory_flag,
            "citation": req.source_citation,
        })

    gaps = [r for r in results if r["status"] == "Gap"]
    return {
        "regulation_id": regulation_id,
        "ruleset_version": version,
        "reporting_year": reporting_year,
        "requirements_assessed": len(results),
        "gaps": len(gaps),
        "gap_detail": gaps[:40],
        "evidenced": len([r for r in results if r["status"] == "Evidenced"]),
        "manual_review": len([r for r in results if r["status"] == "Manual review"]),
    }


@tool(
    name="framework_coverage",
    description=(
        "Report which regulatory frameworks are loaded and how complete each "
        "requirement pack is. Call before claiming framework coverage — the "
        "packs are partial extracts, not complete corpora."
    ),
    schema=_obj({}),
    capability=rbac.VIEW_DEAL,
    deal_arg=None,
)
def _framework_coverage(session, principal, **_):
    from esg.frameworks import registry

    return {"frameworks": registry.coverage_report(session)}


@tool(
    name="run_greenwashing_checks",
    description=(
        "Run the assurance checks: group-to-facility reconciliation, restatement "
        "detection, assurance-scope gaps, and target-progress divergence. Each "
        "finding points at specific disagreeing numbers with document citations. "
        "This is the highest-value analysis for a diligence exercise."
    ),
    schema=_obj({**_DEAL, **_COMPANY, "reporting_year": {"type": "integer"}},
                required=["deal_id", "company_id", "reporting_year"]),
    capability=rbac.RUN_ASSESSMENT,
)
def _greenwashing(session, principal, deal_id, company_id, reporting_year, **_):
    from esg.assurance import greenwashing

    findings = greenwashing.run_all(session, company_id, reporting_year)
    return {"findings": findings, "count": len(findings),
            "by_severity": _tally(findings, "severity")}


@tool(
    name="quantify_exposure",
    description=(
        "Quantify the financial exposure of a finding. Prefers observed amounts "
        "(levied penalties, booked provisions) over the judgement model. The "
        "judgement model returns an INDICATIVE RANGE and never a point estimate, "
        "because its parameters are uncalibrated — report it as a range and say "
        "it is indicative. The run must be reviewed by a Manager before it can "
        "enter any deliverable; this tool does not review it."
    ),
    schema=_obj({
        **_DEAL, **_COMPANY,
        "finding_id": {"type": "string"},
        "severity": {"type": "string", "enum": ["Critical", "High", "Medium", "Low"]},
        "impact_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "use_penalties": {"type": "boolean",
                          "description": "Sum the company's recorded legal penalties as the basis"},
    }, required=["deal_id", "company_id", "finding_id", "severity", "impact_score"]),
    capability=rbac.RUN_ASSESSMENT,
    mutates=True,
)
def _quantify(session, principal, deal_id, company_id, finding_id, severity,
              impact_score, use_penalties=False, **_):
    from esg.db import repository
    from esg.db.models import LegalPenalty
    from esg.methodology import exposure

    penalties = None
    if use_penalties:
        penalties = repository.fetch_all(
            session, LegalPenalty, LegalPenalty.company_id == company_id
        )

    run, result = exposure.quantify(
        session,
        {"finding_id": finding_id, "severity": severity, "impact_score": impact_score},
        company_id=company_id, deal_id=deal_id, evidence_penalties=penalties,
    )
    presentation = exposure.present(run)
    return {
        "exposure_run_id": run.exposure_run_id,
        "method": result["method"],
        "basis": result["basis"],
        "disclosure": result["disclosure"],
        "presentation": presentation["label"],
        "low_usd": result["low_usd"],
        "high_usd": result["high_usd"],
        "point_estimate_usd": result["point_estimate_usd"],
        "basis_note": result["basis_note"],
        "reviewed": False,
        "note": "Not reviewed. A Manager must review this run before it is reportable.",
    }


@tool(
    name="benchmark_metric",
    description=(
        "Assess the peer cohort available for a metric: how many peers, what "
        "provenance, and whether it is publishable. The bundled peer set is "
        "synthetic and NOT publishable — if provenance is 'illustrative', say so "
        "explicitly and do not present percentiles as evidence."
    ),
    schema=_obj({
        "metric_code": {"type": "string"},
        "industry": {"type": "string"},
        "country": {"type": "string"},
        "reporting_year": {"type": "integer"},
    }, required=["metric_code"]),
    capability=rbac.VIEW_DEAL,
    deal_arg=None,
)
def _benchmark(session, principal, metric_code, industry=None, country=None,
               reporting_year=None, **_):
    from esg.benchmarks import provenance

    cohort = provenance.cohort_provenance(
        session, metric_code, industry=industry, country=country,
        reporting_year=reporting_year,
    )
    cohort["sufficiency"] = provenance.sufficiency(cohort)
    return cohort


@tool(
    name="scope3_inventory",
    description=(
        "Scope 3 inventory for a company: emissions by GHG Protocol category, "
        "how much is measured versus estimated from spend, and which material "
        "categories are not reported. Weight conclusions by measured_share — an "
        "unreported category is a named gap, not a zero."
    ),
    schema=_obj({**_DEAL, **_COMPANY, "industry": {"type": "string"}},
                required=["deal_id", "company_id"]),
    capability=rbac.VIEW_DEAL,
)
def _scope3(session, principal, deal_id, company_id, industry=None, **_):
    from esg.analysis import scope3

    return scope3.inventory(session, company_id, industry=industry)


@tool(
    name="supplier_concentration",
    description=(
        "Supply-chain concentration and supplier ESG risk: spend concentration, "
        "human-rights risk ratings, and critical suppliers without a completed "
        "audit. Returns findings ready to raise as information requests."
    ),
    schema=_obj({**_DEAL, **_COMPANY, "top_n": {"type": "integer"}},
                required=["deal_id", "company_id"]),
    capability=rbac.VIEW_DEAL,
)
def _supplier_concentration(session, principal, deal_id, company_id, top_n=5, **_):
    from esg.analysis import scope3

    return scope3.supplier_concentration(session, company_id, top_n=top_n)


# ════════════════════════════════════════════════════════════════════
#  Acting on gaps
# ════════════════════════════════════════════════════════════════════

@tool(
    name="raise_information_request",
    description=(
        "Raise an information request against the target for a gap you found. "
        "Use this whenever an analysis reveals missing evidence — an unreported "
        "Scope 3 category, an unevidenced requirement, an unaudited critical "
        "supplier. This is how a gap becomes a tracked action rather than a "
        "sentence in a report."
    ),
    schema=_obj({
        **_DEAL, **_COMPANY,
        "title": {"type": "string", "description": "What to ask the target for"},
        "detail": {"type": "string", "description": "Why it is needed, and what would satisfy it"},
        "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "linked_requirement_id": {"type": "string"},
    }, required=["deal_id", "company_id", "title"]),
    capability=rbac.RAISE_IR,
    mutates=True,
)
def _raise_ir(session, principal, deal_id, company_id, title, detail=None,
              priority="Medium", linked_requirement_id=None, **_):
    from esg.deal import information_requests as irs

    request = irs.raise_request(
        session, deal_id, company_id, title, detail=detail, priority=priority,
        linked_requirement_id=linked_requirement_id,
    )
    return {"ir_id": request.ir_id, "reference": request.reference,
            "title": request.title, "priority": request.priority,
            "status": request.status}


@tool(
    name="list_information_requests",
    description=(
        "List the deal's information requests and what is still outstanding. "
        "Call before raising a new one to avoid duplicates, and at the end of a "
        "run to report what the target still owes."
    ),
    schema=_obj(_DEAL, required=["deal_id"]),
    capability=rbac.VIEW_DEAL,
)
def _list_irs(session, principal, deal_id, **_):
    from esg.deal import information_requests as irs

    outstanding = irs.outstanding_at_signing(session, deal_id)
    return {
        "register": irs.register(session, deal_id),
        "outstanding_count": outstanding["count"],
        "note": outstanding["note"],
    }


def _tally(items, key):
    counts = {}
    for item in items:
        value = item.get(key)
        counts[value] = counts.get(value, 0) + 1
    return counts


def describe_surface():
    """Human-readable tool inventory, for the UI and for tests."""
    return [
        {"name": t.name, "capability": t.capability, "mutates": t.mutates,
         "description": t.description.split(".")[0] + "."}
        for t in sorted(_REGISTRY.values(), key=lambda t: t.name)
    ]
