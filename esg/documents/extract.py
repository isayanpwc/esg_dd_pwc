"""
Metric extraction with page-level citations.

Output is deliberately *candidates*, not metrics. Each candidate records the
document, the page, the character span and the surrounding snippet, so a
reviewer can see exactly what the machine read before anything enters
esg_metric_data. Nothing is promoted without an explicit human accept
(esg.documents.promote).

The matcher is rule-based on purpose: patterns are inspectable and their
behaviour is reproducible months later when a figure is challenged. An LLM
pass can enrich this — the prompt builder is in esg.documents.llm_assist —
but the deterministic layer stands alone and is what the tests pin.
"""

import re
import uuid

from sqlalchemy import select

from esg import clock
from esg.db.models import DocumentPage, EsgDocumentRegister, MetricCandidate
from esg.db.scope import require_principal
from esg.security import audit, rbac  # noqa: F401

# ── unit and scale vocabulary ──

SCALE_WORDS = {
    "thousand": 1e3, "thousands": 1e3, "'000": 1e3, "k": 1e3,
    "lakh": 1e5, "lakhs": 1e5,
    "million": 1e6, "millions": 1e6, "mn": 1e6, "mm": 1e6,
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "billion": 1e9, "bn": 1e9,
}

UNIT_ALIASES = {
    "tco2e": "tCO2e", "tco2-e": "tCO2e", "tco2": "tCO2e",
    "t co2e": "tCO2e", "tonnes co2e": "tCO2e", "mtco2e": "MtCO2e",
    "ktco2e": "ktCO2e", "kt co2e": "ktCO2e",
    "mwh": "MWh", "gwh": "GWh", "kwh": "kWh", "gj": "GJ", "tj": "TJ",
    "kl": "kL", "ml": "ML", "m3": "m3", "cubic metres": "m3", "kilolitres": "kL",
    "%": "%", "percent": "%", "per cent": "%", "pct": "%",
    "tonnes": "t", "tonne": "t", "mt": "t", "metric tonnes": "t",
    "hours": "hours", "hrs": "hours", "number": "count", "nos": "count",
}

# Unit conversions to the metric master's expected unit.
UNIT_CONVERSIONS = {
    ("ktCO2e", "tCO2e"): 1e3,
    ("MtCO2e", "tCO2e"): 1e6,
    ("GWh", "MWh"): 1e3,
    ("kWh", "MWh"): 1e-3,
    ("GJ", "MWh"): 1 / 3.6,
    ("TJ", "MWh"): 1000 / 3.6,
    ("ML", "kL"): 1e3,
}

# ── metric patterns ──
#
# Each entry: metric_code -> (regex alternatives, expected unit, pillar).
# Patterns are intentionally narrow; a near-miss should produce no candidate
# rather than a wrong one, because a false figure costs more than a gap.

METRIC_PATTERNS = {
    "ENV_SCOPE1": (
        [r"scope[\s\-]*1(?:\s*\(?direct\)?)?(?:\s+(?:ghg\s+)?emissions)?",
         r"direct\s+(?:ghg\s+)?emissions\s*\(?\s*scope[\s\-]*1\s*\)?"],
        "tCO2e", "Environment",
    ),
    "ENV_SCOPE2": (
        [r"scope[\s\-]*2(?:\s*\(?(?:indirect|market[\s\-]based|location[\s\-]based)\)?)?"
         r"(?:\s+(?:ghg\s+)?emissions)?",
         r"indirect\s+(?:ghg\s+)?emissions\s*\(?\s*scope[\s\-]*2\s*\)?"],
        "tCO2e", "Environment",
    ),
    "ENV_SCOPE3": (
        [r"scope[\s\-]*3(?:\s+(?:ghg\s+)?emissions)?",
         r"value\s+chain\s+emissions"],
        "tCO2e", "Environment",
    ),
    "ENV_ENERGY_TOTAL": (
        [r"total\s+energy\s+(?:consumption|consumed|use)",
         r"energy\s+consumption\s*\(?\s*total\s*\)?"],
        "MWh", "Environment",
    ),
    "ENV_RENEW_PCT": (
        [r"(?:share|percentage|proportion)\s+of\s+renewable\s+(?:energy|electricity)",
         r"renewable\s+(?:energy|electricity)\s+(?:share|percentage|mix)"],
        "%", "Environment",
    ),
    "ENV_WATER_WITHDRAWAL": (
        [r"(?:total\s+)?water\s+(?:withdrawal|withdrawn|consumption)"],
        "kL", "Environment",
    ),
    "ENV_WASTE_TOTAL": (
        [r"total\s+waste\s+generated", r"waste\s+generation\s*\(?\s*total\s*\)?"],
        "t", "Environment",
    ),
    "ENV_EWASTE": (
        [r"e[\s\-]*waste\s+(?:generated|recycled)?"],
        "t", "Environment",
    ),
    "SOC_FEMALE_PCT": (
        [r"(?:percentage|share|proportion)\s+of\s+(?:female|women)\s+(?:employees|workforce)",
         r"(?:female|women)\s+(?:employees|workforce)\s+(?:percentage|share|ratio)",
         r"gender\s+diversity\s*(?:ratio)?"],
        "%", "Social",
    ),
    "SOC_ATTRITION": (
        [r"(?:employee\s+)?attrition\s+rate", r"(?:voluntary\s+)?turnover\s+rate"],
        "%", "Social",
    ),
    "SOC_TRAINING_HOURS": (
        [r"(?:average\s+)?training\s+hours(?:\s+per\s+employee)?"],
        "hours", "Social",
    ),
    "SOC_LTIFR": (
        [r"ltifr", r"lost\s+time\s+injury\s+frequency\s+rate"],
        "count", "Social",
    ),
    "SOC_FATALITIES": (
        [r"(?:number\s+of\s+)?fatalities", r"work[\s\-]*related\s+fatalities"],
        "count", "Social",
    ),
    "GOV_BOARD_INDEP_PCT": (
        [r"(?:percentage|share|proportion)\s+of\s+independent\s+directors",
         r"independent\s+directors?\s+(?:percentage|share|ratio)"],
        "%", "Governance",
    ),
    "GOV_WOMEN_BOARD_PCT": (
        [r"(?:percentage|share|proportion)\s+of\s+women\s+(?:on\s+the\s+board|directors)",
         r"women\s+(?:on\s+)?board\s+(?:percentage|share|representation)"],
        "%", "Governance",
    ),
}

_NUMBER = r"\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?|\(?-?\d+(?:\.\d+)?\)?"
_YEAR = r"(?:FY\s*)?(?:19|20)\d{2}(?:\s*[-/]\s*\d{2,4})?"
_UNIT_ALTERNATIVES = "|".join(
    sorted((re.escape(u) for u in UNIT_ALIASES), key=len, reverse=True)
)
# Horizontal whitespace only. A unit or scale on the *next* line belongs to the
# next disclosure, not this one — matching across newlines is how "fatalities: 0"
# ends up wearing the "%" from the line below it.
_HSPACE = r"[^\S\n]*"
_SCALE_ALTERNATIVES = "|".join(
    sorted((re.escape(s) for s in SCALE_WORDS), key=len, reverse=True)
)

# How far past the label we will look for the value.
_WINDOW = 140


def normalise_unit(raw):
    if not raw:
        return None
    key = raw.strip().lower()
    return UNIT_ALIASES.get(key, raw.strip())


def parse_number(raw):
    text = raw.strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def convert_to_expected(value, unit, expected_unit):
    """Returns (value, unit, converted_flag). Unknown pairs are left alone so a
    mismatch surfaces to the reviewer instead of being silently rescaled."""
    if value is None or not unit or not expected_unit or unit == expected_unit:
        return value, unit, False
    factor = UNIT_CONVERSIONS.get((unit, expected_unit))
    if factor is None:
        return value, unit, False
    return value * factor, expected_unit, True


def resolve_fiscal_year(label):
    """Closing calendar year of a fiscal-year label.

    Indian and UK disclosures label a year as FY2023-24 or FY24, meaning the
    year ending 2024. Reading that as 2023 silently shifts a whole disclosure
    by one period, which then shows up as a fabricated year-on-year movement.
    """
    text = str(label or "").upper().replace("FY", "").strip()
    match = re.fullmatch(r"((?:19|20)\d{2})\s*[-/]\s*(\d{2,4})", text)
    if match:
        tail = match.group(2)
        return int(tail) if len(tail) == 4 else int(match.group(1)[:2] + tail)
    if re.fullmatch(r"(?:19|20)\d{2}", text):
        return int(text)
    return None


def find_year(text, span, fallback=None):
    """Reporting year for a match: the nearest fiscal-year label, else the
    nearest plain year, else the document's declared year."""
    start, end = span
    window = text[max(0, start - 120):min(len(text), end + 140)]

    ranges = re.findall(r"(?:FY\s*)?((?:19|20)\d{2}\s*[-/]\s*\d{2,4})", window)
    if ranges:
        resolved = resolve_fiscal_year(ranges[-1])
        if resolved:
            return resolved

    short = re.findall(r"FY\s*(\d{2})(?!\d)", window)
    if short:
        return 2000 + int(short[-1])

    years = re.findall(r"((?:19|20)\d{2})", window)
    if years:
        return int(years[-1])
    return fallback


def extract_from_text(text, page_number, reporting_year=None,
                      metric_patterns=None):
    """Find metric candidates in one page of text.

    Returns dicts, not ORM objects, so this is unit-testable without a database.
    """
    if not text:
        return []

    patterns = metric_patterns or METRIC_PATTERNS
    lowered = text.lower()
    found = []

    for metric_code, (alternatives, expected_unit, pillar) in patterns.items():
        for alternative in alternatives:
            for label in re.finditer(alternative, lowered):
                tail = text[label.end():label.end() + _WINDOW]
                value_match = re.search(
                    rf"(?P<scale_pre>{_SCALE_ALTERNATIVES})?{_HSPACE}"
                    rf"(?P<number>{_NUMBER}){_HSPACE}"
                    rf"(?:(?P<scale>{_SCALE_ALTERNATIVES})(?!\w))?{_HSPACE}"
                    rf"(?:(?P<unit>{_UNIT_ALTERNATIVES})(?!\w))?",
                    tail, re.IGNORECASE,
                )
                if not value_match or not value_match.group("number"):
                    continue

                raw_number = value_match.group("number")
                value = parse_number(raw_number)
                if value is None:
                    continue

                # A year sitting where the value should be is a column header,
                # not a measurement.
                if re.fullmatch(r"(?:19|20)\d{2}", raw_number.strip()):
                    continue

                scale_word = (value_match.group("scale")
                              or value_match.group("scale_pre") or "")
                scale = SCALE_WORDS.get(scale_word.strip().lower(), 1.0)
                unit = normalise_unit(value_match.group("unit"))
                scaled = value * scale

                converted, final_unit, was_converted = convert_to_expected(
                    scaled, unit, expected_unit
                )

                start = label.start()
                end = label.end() + value_match.end()
                confidence = _score(
                    unit=unit, expected_unit=expected_unit,
                    had_scale=bool(scale_word), distance=value_match.start(),
                    alternative_index=alternatives.index(alternative),
                    converted=was_converted,
                )

                found.append({
                    "metric_code": metric_code,
                    "esg_pillar": pillar,
                    "page_number": page_number,
                    "raw_value": raw_number + (f" {scale_word}" if scale_word else "")
                    + (f" {unit}" if unit else ""),
                    "value": round(converted, 6) if converted is not None else None,
                    "unit": final_unit or expected_unit,
                    "reporting_year": find_year(text, (start, end), reporting_year),
                    "snippet": _snippet(text, start, end),
                    "char_start": start,
                    "char_end": end,
                    "match_rule": f"{metric_code}#{alternatives.index(alternative)}",
                    "confidence": confidence,
                    "unit_converted": was_converted,
                })

    return _deduplicate(found)


def _score(unit, expected_unit, had_scale, distance, alternative_index, converted):
    """Confidence in [0, 1]. Explainable by construction — each term is a
    property a reviewer can check, not a learned weight."""
    score = 0.55
    if unit and expected_unit and unit == expected_unit:
        score += 0.25
    elif converted:
        score += 0.15
    elif unit:
        score -= 0.05
    else:
        score -= 0.10

    if distance <= 12:
        score += 0.12
    elif distance <= 40:
        score += 0.05
    else:
        score -= 0.08

    if had_scale:
        score += 0.03
    if alternative_index > 0:
        score -= 0.04
    return round(max(0.05, min(0.98, score)), 3)


def _snippet(text, start, end, pad=90):
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    fragment = text[left:right].replace("\n", " ")
    return re.sub(r"\s+", " ", fragment).strip()


def _deduplicate(candidates):
    """Keep the most confident candidate per (metric, year, value) on a page."""
    best = {}
    for candidate in candidates:
        key = (candidate["metric_code"], candidate["reporting_year"],
               candidate["value"])
        incumbent = best.get(key)
        if incumbent is None or candidate["confidence"] > incumbent["confidence"]:
            best[key] = candidate
    return sorted(best.values(),
                  key=lambda c: (c["page_number"], -c["confidence"]))


# ── persistence ──

def extract_document(session, document_id, min_confidence=0.35):
    """Run extraction across a document's pages and persist the candidates."""
    principal = require_principal()

    document = session.get(EsgDocumentRegister, document_id)
    if document is None:
        raise ValueError(f"Document {document_id!r} not found or not in scope.")
    rbac.check(rbac.INGEST_DATA, deal_id=document.deal_id, principal=principal)

    pages = session.execute(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    ).scalars().all()

    existing = {
        (c.metric_code, c.page_number, c.char_start)
        for c in session.execute(
            select(MetricCandidate).where(MetricCandidate.document_id == document_id)
        ).scalars()
    }

    created = []
    for page in pages:
        for found in extract_from_text(
            page.text, page.page_number, reporting_year=document.reporting_year
        ):
            if found["confidence"] < min_confidence:
                continue
            key = (found["metric_code"], found["page_number"], found["char_start"])
            if key in existing:
                continue
            candidate = MetricCandidate(
                candidate_id=uuid.uuid4().hex[:32],
                deal_id=document.deal_id,
                document_id=document_id,
                page_number=found["page_number"],
                company_id=document.company_id,
                metric_code=found["metric_code"],
                reporting_year=found["reporting_year"],
                raw_value=found["raw_value"],
                value=found["value"],
                unit=found["unit"],
                snippet=found["snippet"],
                char_start=found["char_start"],
                char_end=found["char_end"],
                match_rule=found["match_rule"],
                confidence=found["confidence"],
                extraction_method=page.extraction_method,
                status="Pending",
            )
            session.add(candidate)
            created.append(candidate)
            existing.add(key)

    audit.record(
        session, principal.username, "document.extracted",
        entity_type="esg_document_register", entity_id=document_id,
        deal_id=document.deal_id,
        detail={"candidates": len(created), "pages": len(pages)},
    )
    session.flush()
    return created


def pending_candidates(session, deal_id=None, document_id=None, min_confidence=None):
    stmt = select(MetricCandidate).where(MetricCandidate.status == "Pending")
    if deal_id:
        stmt = stmt.where(MetricCandidate.deal_id == deal_id)
    if document_id:
        stmt = stmt.where(MetricCandidate.document_id == document_id)
    if min_confidence is not None:
        stmt = stmt.where(MetricCandidate.confidence >= min_confidence)
    return session.execute(
        stmt.order_by(MetricCandidate.confidence.desc())
    ).scalars().all()
