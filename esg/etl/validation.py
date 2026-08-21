"""
The validation gate.

Every source row is checked before it reaches a canonical table. A row that
fails is quarantined with its reasons rather than dropped, because in due
diligence a row you silently discarded is worse than one you never had — the
analysis looks complete while missing evidence.

Severity decides the outcome:
  error   -> the row is quarantined, never loaded
  warning -> the row loads, and the warning is recorded against the run

Checks are declared per target table as data, so adding a canonical table means
adding a spec, not editing this logic.
"""

import math
import re
from dataclasses import dataclass, field

from esg.db import models

ERROR = "error"
WARNING = "warning"


@dataclass
class Issue:
    column: str
    rule: str
    message: str
    severity: str = ERROR

    def as_dict(self):
        return {"column": self.column, "rule": self.rule,
                "message": self.message, "severity": self.severity}


@dataclass
class RowResult:
    row_number: int
    values: dict
    issues: list = field(default_factory=list)

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self):
        return not self.errors


@dataclass
class TableSpec:
    """What a canonical table requires of an incoming row."""

    model: type
    required: tuple = ()
    numeric: tuple = ()
    integer: tuple = ()
    year: tuple = ()
    boolean: tuple = ()
    date: tuple = ()
    enums: dict = field(default_factory=dict)
    non_negative: tuple = ()
    max_len: dict = field(default_factory=dict)
    # Columns that must resolve to an existing row elsewhere.
    references: dict = field(default_factory=dict)  # column -> (model, attribute)


_PILLARS = ("Environment", "Social", "Governance", "E", "S", "G")
_TRUE = {"true", "yes", "y", "1", "t"}
_FALSE = {"false", "no", "n", "0", "f"}

SPECS = {
    "esg_metric_data": TableSpec(
        model=models.EsgMetricData,
        required=("record_id", "company_id", "metric_code", "reporting_year"),
        numeric=("value", "confidence_score", "data_quality_score"),
        year=("reporting_year",),
        boolean=("is_estimated", "is_audited", "human_verified"),
        integer=("source_page",),
        max_len={"unit": 64, "metric_code": 64},
        references={
            "company_id": (models.CompanyMaster, "company_id"),
            "metric_code": (models.EsgMetricMaster, "metric_code"),
        },
    ),
    "company_financials": TableSpec(
        model=models.CompanyFinancials,
        required=("company_id", "reporting_year"),
        numeric=("annual_revenue",),
        integer=("employee_count",),
        year=("reporting_year",),
        non_negative=("annual_revenue", "employee_count"),
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "company_master": TableSpec(
        model=models.CompanyMaster,
        required=("company_id", "company_name"),
        max_len={"company_name": 255, "country": 128},
    ),
    "legal_penalty": TableSpec(
        model=models.LegalPenalty,
        required=("penalty_id", "company_id"),
        numeric=("amount",),
        non_negative=("amount",),
        date=("filed_date", "resolution_date"),
        max_len={"currency": 8},
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "controversy_record": TableSpec(
        model=models.ControversyRecord,
        required=("controversy_id", "company_id"),
        date=("event_date",),
        enums={"esg_pillar": _PILLARS},
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "esg_target": TableSpec(
        model=models.EsgTarget,
        required=("target_id", "company_id"),
        numeric=("base_value", "target_value", "current_value", "progress_pct"),
        year=("base_year", "target_year"),
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "compliance_assessment": TableSpec(
        model=models.ComplianceAssessment,
        required=("compliance_id", "company_id", "requirement_id"),
        year=("reporting_year",),
        integer=("evidence_page",),
        date=("target_date",),
        references={
            "company_id": (models.CompanyMaster, "company_id"),
            "requirement_id": (models.RegulatoryRequirement, "requirement_id"),
        },
    ),
    "supplier_esg_assessment": TableSpec(
        model=models.SupplierEsgAssessment,
        required=("supplier_assessment_id", "supplier_id", "company_id"),
        numeric=("environment_score", "social_score", "governance_score",
                 "overall_esg_score", "scope3_emissions_tco2e"),
        non_negative=("scope3_emissions_tco2e",),
        date=("assessment_date",),
        references={"supplier_id": (models.SupplierMaster, "supplier_id")},
    ),
    "certification": TableSpec(
        model=models.Certification,
        required=("certification_id", "company_id"),
        date=("issue_date", "expiry_date"),
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "facility_master": TableSpec(
        model=models.FacilityMaster,
        required=("facility_id", "company_id"),
        integer=("employee_count",),
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    # ── reference tables ──
    # Parents for the foreign-key checks above. Without specs the loader skips
    # them, and every child row then fails its referential check.
    "esg_metric_master": TableSpec(
        model=models.EsgMetricMaster,
        required=("metric_code", "metric_name"),
        boolean=("is_intensity",),
        enums={"direction": ("higher", "lower")},
        max_len={"metric_code": 64, "unit": 64},
    ),
    "supplier_master": TableSpec(
        model=models.SupplierMaster,
        required=("supplier_id", "supplier_name"),
        numeric=("annual_spend",),
        non_negative=("annual_spend",),
        max_len={"spend_currency": 8},
    ),
    "regulation_master": TableSpec(
        model=models.RegulationMaster,
        required=("regulation_id", "regulation_name"),
        date=("effective_date",),
    ),
    "regulatory_requirement": TableSpec(
        model=models.RegulatoryRequirement,
        required=("requirement_id", "regulation_id", "requirement_code",
                  "requirement_name"),
        date=("effective_from", "effective_to"),
        references={"regulation_id": (models.RegulationMaster, "regulation_id")},
    ),
    "fx_rate_reference": TableSpec(
        model=models.FxRateReference,
        required=("from_currency", "to_currency", "rate", "rate_date"),
        numeric=("rate",),
        non_negative=("rate",),
        date=("rate_date",),
        max_len={"from_currency": 8, "to_currency": 8},
    ),
    "deal_master": TableSpec(
        model=models.DealMaster,
        required=("deal_id", "deal_name", "company_id"),
        date=("start_date", "target_close_date"),
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "esg_risk_opportunity": TableSpec(
        model=models.EsgRiskOpportunity,
        required=("finding_id", "company_id"),
        numeric=("overall_score", "financial_impact"),
        integer=("likelihood_score", "impact_score"),
        enums={"esg_pillar": _PILLARS},
        references={"company_id": (models.CompanyMaster, "company_id")},
    ),
    "esg_document_register": TableSpec(
        model=models.EsgDocumentRegister,
        required=("document_id", "company_id", "document_name"),
        year=("reporting_year",),
        date=("document_date",),
    ),
}


def _is_blank(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == "" or str(value).strip().lower() in {"nan", "none", "null"}


def coerce_number(value):
    """Parse a number the way source spreadsheets actually write them:
    '1,234.5', '(890)' for negative, '45%', '  12 '."""
    text = str(value).strip().replace(",", "").replace("%", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    number = float(text)
    return -number if negative else number


def coerce_bool(value):
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"{value!r} is not a recognisable yes/no value")


def coerce_date(value):
    import pandas as pd

    parsed = pd.to_datetime(value, errors="raise", dayfirst=False)
    return parsed.date() if hasattr(parsed, "date") else parsed


def validate_row(spec, row_number, values, reference_index=None):
    """Check and coerce one row. Returns a RowResult with coerced values."""
    result = RowResult(row_number=row_number, values=dict(values))
    coerced = result.values

    for column in spec.required:
        if _is_blank(coerced.get(column)):
            result.issues.append(Issue(column, "required",
                                       f"{column} is required and was empty"))

    for column in spec.numeric + spec.integer + spec.year:
        raw = coerced.get(column)
        if _is_blank(raw):
            coerced[column] = None
            continue
        try:
            number = coerce_number(raw)
        except (TypeError, ValueError):
            result.issues.append(Issue(column, "numeric",
                                       f"{column}={raw!r} is not a number"))
            continue
        if column in spec.integer or column in spec.year:
            if abs(number - round(number)) > 1e-9:
                result.issues.append(Issue(column, "integer",
                                           f"{column}={raw!r} must be a whole number"))
                continue
            number = int(round(number))
        coerced[column] = number

    for column in spec.year:
        year = coerced.get(column)
        if year is None:
            continue
        # A reporting year outside this window is a data-entry error, not a
        # long-range disclosure.
        if not 1990 <= year <= 2100:
            result.issues.append(Issue(column, "year_range",
                                       f"{column}={year} is outside 1990–2100"))

    for column in spec.non_negative:
        value = coerced.get(column)
        if isinstance(value, (int, float)) and value < 0:
            result.issues.append(Issue(column, "non_negative",
                                       f"{column}={value} cannot be negative"))

    for column in spec.boolean:
        raw = coerced.get(column)
        if _is_blank(raw):
            coerced[column] = None
            continue
        try:
            coerced[column] = coerce_bool(raw)
        except ValueError as exc:
            result.issues.append(Issue(column, "boolean", str(exc)))

    for column in spec.date:
        raw = coerced.get(column)
        if _is_blank(raw):
            coerced[column] = None
            continue
        try:
            coerced[column] = coerce_date(raw)
        except Exception:
            result.issues.append(Issue(column, "date",
                                       f"{column}={raw!r} is not a recognisable date"))

    for column, allowed in spec.enums.items():
        raw = coerced.get(column)
        if _is_blank(raw):
            continue
        if str(raw).strip() not in allowed:
            result.issues.append(Issue(
                column, "enum",
                f"{column}={raw!r} is not one of {', '.join(allowed)}",
                severity=WARNING,
            ))

    for column, limit in spec.max_len.items():
        raw = coerced.get(column)
        if not _is_blank(raw) and len(str(raw)) > limit:
            result.issues.append(Issue(column, "max_length",
                                       f"{column} exceeds {limit} characters"))

    if reference_index is not None:
        for column, (model, _attr) in spec.references.items():
            raw = coerced.get(column)
            if _is_blank(raw):
                continue
            known = reference_index.get(model.__tablename__)
            if known is not None and str(raw).strip() not in known:
                result.issues.append(Issue(
                    column, "foreign_key",
                    f"{column}={raw!r} does not exist in {model.__tablename__}",
                ))

    # Normalise remaining blanks so NOT NULL columns fail the required check
    # above rather than the database.
    for key, value in list(coerced.items()):
        if _is_blank(value):
            coerced[key] = None

    return result


def build_reference_index(session, spec):
    """Load the key sets this spec's foreign keys point at, once per run."""
    from esg.db import repository

    index = {}
    for _column, (model, attribute) in spec.references.items():
        table = model.__tablename__
        if table in index:
            continue
        column = getattr(model, attribute)
        rows = session.execute(_select_keys(column)).scalars().all()
        index[table] = {str(value) for value in rows if value is not None}
    return index


def _select_keys(column):
    from sqlalchemy import select

    return select(column)
