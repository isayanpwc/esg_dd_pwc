"""
Canonical ESG schema plus the platform tables the agents depend on.

Two families of table live here:

* Deal-scoped tables inherit DealScoped and carry a non-null deal_id. Every
  read of these goes through esg.db.scope, which refuses to run without an
  authenticated principal and injects the caller's permitted deal ids. On
  Postgres the same restriction is additionally enforced by row-level
  security policies (see migrations/versions/0002_row_level_security.py).

* Reference tables (regulations, metric definitions, FX rates, peer
  benchmarks) are deal-independent and readable by any authenticated user.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from esg.db.crypto import Encrypted
from esg import clock


class Base(DeclarativeBase):
    pass


class DealScoped:
    """Marker + column for every table that holds deal-confidential data."""

    deal_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)


# ════════════════════════════════════════════════════════════════════
#  Identity, provisioning and access control
# ════════════════════════════════════════════════════════════════════

ROLES = ("Admin", "Manager", "Analyst", "Viewer")
PERMISSION_LEVELS = ("Owner", "Editor", "Reviewer", "ReadOnly")


class UserAccount(Base):
    __tablename__ = "user_account"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Encrypted PII. email_hash is a blind index so login can look the user
    # up without the plaintext being queryable.
    email: Mapped[str] = mapped_column(Encrypted(512), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(Encrypted(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    provisioned_by: Mapped[str] = mapped_column(String(32), nullable=True)
    idp_subject: Mapped[str] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now, nullable=False)
    last_login_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="ck_user_role"),
    )


class UserInvite(Base):
    """Admin-issued invitation. The only path to a new account."""

    __tablename__ = "user_invite"

    invite_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[str] = mapped_column(Encrypted(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now, nullable=False)

    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="ck_invite_role"),
    )


class DealAccessControl(Base):
    """Which users may see which deal. Consulted on every scoped read."""

    __tablename__ = "deal_access_control"

    access_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    permission_level: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(32), nullable=True)
    granted_date: Mapped[date] = mapped_column(Date, nullable=True)
    revoked_date: Mapped[date] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("deal_id", "user_id", "granted_date", name="uq_acl_grant"),
        CheckConstraint(f"permission_level IN {PERMISSION_LEVELS}", name="ck_acl_level"),
    )


class AuditEvent(Base):
    """Append-only, hash-chained audit log.

    Rows are never updated or deleted by application code; prev_hash/entry_hash
    make silent tampering detectable (esg.security.audit.verify_chain).
    """

    __tablename__ = "audit_event"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=True)
    deal_id: Mapped[str] = mapped_column(String(32), nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


# ════════════════════════════════════════════════════════════════════
#  Reference data (deal-independent)
# ════════════════════════════════════════════════════════════════════

class CompanyMaster(Base):
    __tablename__ = "company_master"

    company_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_company: Mapped[str] = mapped_column(String(255), nullable=True)
    industry: Mapped[str] = mapped_column(String(128), nullable=True)
    country: Mapped[str] = mapped_column(String(128), nullable=True)


class CompanyFinancials(Base):
    __tablename__ = "company_financials"

    company_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reporting_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    annual_revenue: Mapped[float] = mapped_column(Float, nullable=True)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=True)
    reporting_currency: Mapped[str] = mapped_column(String(8), nullable=True)


class FacilityMaster(Base):
    __tablename__ = "facility_master"

    facility_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    facility_name: Mapped[str] = mapped_column(String(255), nullable=True)
    facility_type: Mapped[str] = mapped_column(String(64), nullable=True)
    country: Mapped[str] = mapped_column(String(128), nullable=True)
    city: Mapped[str] = mapped_column(String(128), nullable=True)
    ownership_type: Mapped[str] = mapped_column(String(64), nullable=True)
    operational_status: Mapped[str] = mapped_column(String(64), nullable=True)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=True)


class EsgMetricMaster(Base):
    __tablename__ = "esg_metric_master"

    metric_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    esg_pillar: Mapped[str] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(128), nullable=True)
    unit: Mapped[str] = mapped_column(String(64), nullable=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    is_intensity: Mapped[bool] = mapped_column(Boolean, default=False)
    intensity_denominator: Mapped[str] = mapped_column(String(64), nullable=True)


class RegulationMaster(Base):
    __tablename__ = "regulation_master"

    regulation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    regulation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(128), nullable=True)
    regulatory_body: Mapped[str] = mapped_column(String(255), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=True)
    applicable_industry: Mapped[str] = mapped_column(String(255), nullable=True)
    mandatory_flag: Mapped[str] = mapped_column(String(8), nullable=True)
    regulation_version: Mapped[str] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=True)


class RegulatoryRequirement(Base):
    """Effective-dated requirement. A framework version is the set of rows
    whose [effective_from, effective_to) window contains the assessment date.
    """

    __tablename__ = "regulatory_requirement"

    requirement_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    regulation_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    requirement_code: Mapped[str] = mapped_column(String(64), nullable=False)
    requirement_name: Mapped[str] = mapped_column(String(512), nullable=False)
    requirement_description: Mapped[str] = mapped_column(Text, nullable=True)
    required_metric_code: Mapped[str] = mapped_column(String(64), nullable=True)
    required_document: Mapped[str] = mapped_column(String(255), nullable=True)
    mandatory_flag: Mapped[str] = mapped_column(String(8), nullable=True)
    compliance_frequency: Mapped[str] = mapped_column(String(32), nullable=True)
    disclosure_topic: Mapped[str] = mapped_column(String(255), nullable=True)
    applies_to_industry: Mapped[str] = mapped_column(String(255), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date] = mapped_column(Date, nullable=True)
    ruleset_version: Mapped[str] = mapped_column(String(32), nullable=True)
    source_citation: Mapped[str] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_requirement_effective", "regulation_id", "effective_from", "effective_to"),
    )


class MetricStandardCrosswalk(Base):
    __tablename__ = "metric_standard_crosswalk"

    crosswalk_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reporting_standard: Mapped[str] = mapped_column(String(64), nullable=False)
    standard_disclosure_code: Mapped[str] = mapped_column(String(64), nullable=True)
    standard_disclosure_name: Mapped[str] = mapped_column(String(512), nullable=True)
    unit_conversion_note: Mapped[str] = mapped_column(Text, nullable=True)


class FxRateReference(Base):
    __tablename__ = "fx_rate_reference"

    from_currency: Mapped[str] = mapped_column(String(8), primary_key=True)
    to_currency: Mapped[str] = mapped_column(String(8), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=True)


class PeerBenchmarkData(Base):
    """Peer comparators.

    provenance distinguishes a licensed commercial dataset from the
    illustrative sample shipped for demos; the UI must surface it (see
    esg.benchmarks.provenance).
    """

    __tablename__ = "peer_benchmark_data"

    benchmark_record_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    peer_company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(128), nullable=True)
    country: Mapped[str] = mapped_column(String(128), nullable=True)
    reporting_year: Mapped[int] = mapped_column(Integer, nullable=True)
    metric_code: Mapped[str] = mapped_column(String(64), index=True, nullable=True)
    metric_value: Mapped[float] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(64), nullable=True)
    normalised_value: Mapped[float] = mapped_column(Float, nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=True)
    source_document: Mapped[str] = mapped_column(String(512), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), default="illustrative", nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=True)
    licensed_until: Mapped[date] = mapped_column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "provenance IN ('licensed', 'public_disclosure', 'illustrative')",
            name="ck_benchmark_provenance",
        ),
    )


class SupplierMaster(Base):
    __tablename__ = "supplier_master"

    supplier_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(128), nullable=True)
    tier: Mapped[str] = mapped_column(String(16), nullable=True)
    annual_spend: Mapped[float] = mapped_column(Float, nullable=True)
    spend_currency: Mapped[str] = mapped_column(String(8), nullable=True)
    criticality: Mapped[str] = mapped_column(String(32), nullable=True)


# ════════════════════════════════════════════════════════════════════
#  Deal-scoped data
# ════════════════════════════════════════════════════════════════════

class DealMaster(Base, DealScoped):
    __tablename__ = "deal_master"

    deal_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    deal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    deal_type: Mapped[str] = mapped_column(String(64), nullable=True)
    deal_status: Mapped[str] = mapped_column(String(64), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=True)
    target_close_date: Mapped[date] = mapped_column(Date, nullable=True)
    deal_lead: Mapped[str] = mapped_column(String(128), nullable=True)


class EsgMetricData(Base, DealScoped):
    __tablename__ = "esg_metric_data"

    record_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reporting_year: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(64), nullable=True)
    facility_id: Mapped[str] = mapped_column(String(32), nullable=True)
    source_document_id: Mapped[str] = mapped_column(String(48), nullable=True)
    source_page: Mapped[int] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=True)
    data_quality_score: Mapped[float] = mapped_column(Float, nullable=True)
    is_estimated: Mapped[bool] = mapped_column(Boolean, nullable=True)
    is_audited: Mapped[bool] = mapped_column(Boolean, nullable=True)
    human_verified: Mapped[bool] = mapped_column(Boolean, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=True)
    # Set when a later filing revises a previously reported figure.
    supersedes_record_id: Mapped[str] = mapped_column(String(48), nullable=True)
    restatement_reason: Mapped[str] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_metric_lookup", "deal_id", "company_id", "metric_code", "reporting_year"),
    )


class EsgTarget(Base, DealScoped):
    __tablename__ = "esg_target"

    target_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=True)
    target_name: Mapped[str] = mapped_column(String(512), nullable=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=True)
    base_year: Mapped[int] = mapped_column(Integer, nullable=True)
    base_value: Mapped[float] = mapped_column(Float, nullable=True)
    target_year: Mapped[int] = mapped_column(Integer, nullable=True)
    target_value: Mapped[float] = mapped_column(Float, nullable=True)
    current_value: Mapped[float] = mapped_column(Float, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, nullable=True)
    expected_pct_linear: Mapped[float] = mapped_column(Float, nullable=True)
    on_track_flag: Mapped[str] = mapped_column(String(8), nullable=True)
    sbti_validated_flag: Mapped[str] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=True)
    evidence_document_id: Mapped[str] = mapped_column(String(48), nullable=True)


class ComplianceAssessment(Base, DealScoped):
    __tablename__ = "compliance_assessment"

    compliance_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    requirement_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    reporting_year: Mapped[int] = mapped_column(Integer, nullable=True)
    compliance_status: Mapped[str] = mapped_column(String(32), nullable=True)
    available_value: Mapped[str] = mapped_column(String(255), nullable=True)
    gap_description: Mapped[str] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=True)
    evidence_document_id: Mapped[str] = mapped_column(String(48), nullable=True)
    evidence_page: Mapped[int] = mapped_column(Integer, nullable=True)
    remediation_action: Mapped[str] = mapped_column(Text, nullable=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=True)
    ruleset_version: Mapped[str] = mapped_column(String(32), nullable=True)


class ControversyRecord(Base, DealScoped):
    __tablename__ = "controversy_record"

    controversy_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=True)
    esg_pillar: Mapped[str] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    verified_flag: Mapped[str] = mapped_column(String(8), nullable=True)


class LegalPenalty(Base, DealScoped):
    __tablename__ = "legal_penalty"

    penalty_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    controversy_id: Mapped[str] = mapped_column(String(48), nullable=True)
    case_reference: Mapped[str] = mapped_column(String(255), nullable=True)
    regulator_body: Mapped[str] = mapped_column(String(255), nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(128), nullable=True)
    penalty_type: Mapped[str] = mapped_column(String(64), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=True)
    provision_booked: Mapped[str] = mapped_column(String(8), nullable=True)
    filed_date: Mapped[date] = mapped_column(Date, nullable=True)
    resolution_date: Mapped[date] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)


class EsgRiskOpportunity(Base, DealScoped):
    __tablename__ = "esg_risk_opportunity"

    finding_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    finding_type: Mapped[str] = mapped_column(String(32), nullable=True)
    esg_pillar: Mapped[str] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    likelihood_score: Mapped[int] = mapped_column(Integer, nullable=True)
    impact_score: Mapped[int] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=True)
    financial_impact: Mapped[float] = mapped_column(Float, nullable=True)
    financial_impact_currency: Mapped[str] = mapped_column(String(8), nullable=True)
    priority: Mapped[str] = mapped_column(String(32), nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_document_id: Mapped[str] = mapped_column(String(48), nullable=True)
    evidence_controversy_id: Mapped[str] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=True)


class Certification(Base, DealScoped):
    __tablename__ = "certification"

    certification_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    facility_id: Mapped[str] = mapped_column(String(32), nullable=True)
    certification_name: Mapped[str] = mapped_column(String(255), nullable=True)
    standard_body: Mapped[str] = mapped_column(String(255), nullable=True)
    scope: Mapped[str] = mapped_column(String(255), nullable=True)
    certificate_number: Mapped[str] = mapped_column(String(128), nullable=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=True)
    certifying_body: Mapped[str] = mapped_column(String(255), nullable=True)


class SupplierEsgAssessment(Base, DealScoped):
    __tablename__ = "supplier_esg_assessment"

    supplier_assessment_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    assessment_date: Mapped[date] = mapped_column(Date, nullable=True)
    environment_score: Mapped[float] = mapped_column(Float, nullable=True)
    social_score: Mapped[float] = mapped_column(Float, nullable=True)
    governance_score: Mapped[float] = mapped_column(Float, nullable=True)
    overall_esg_score: Mapped[float] = mapped_column(Float, nullable=True)
    human_rights_risk: Mapped[str] = mapped_column(String(32), nullable=True)
    carbon_data_available: Mapped[str] = mapped_column(String(8), nullable=True)
    audit_status: Mapped[str] = mapped_column(String(64), nullable=True)
    corrective_action_status: Mapped[str] = mapped_column(String(64), nullable=True)
    # Scope 3 / supply-chain depth
    scope3_category: Mapped[str] = mapped_column(String(64), nullable=True)
    scope3_emissions_tco2e: Mapped[float] = mapped_column(Float, nullable=True)
    emissions_basis: Mapped[str] = mapped_column(String(32), nullable=True)


class DataValueHistory(Base):
    __tablename__ = "data_value_history"

    history_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(64), nullable=True)
    change_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    change_reason: Mapped[str] = mapped_column(Text, nullable=True)


# ════════════════════════════════════════════════════════════════════
#  Document intelligence
# ════════════════════════════════════════════════════════════════════

class EsgDocumentRegister(Base, DealScoped):
    __tablename__ = "esg_document_register"

    document_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    facility_id: Mapped[str] = mapped_column(String(32), nullable=True)
    document_name: Mapped[str] = mapped_column(String(512), nullable=False)
    document_type: Mapped[str] = mapped_column(String(128), nullable=True)
    reporting_year: Mapped[int] = mapped_column(Integer, nullable=True)
    source_system: Mapped[str] = mapped_column(String(128), nullable=True)
    file_path: Mapped[str] = mapped_column(Encrypted(1024), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=True)
    document_date: Mapped[date] = mapped_column(Date, nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=True)
    confidentiality_flag: Mapped[str] = mapped_column(String(32), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="Pending", nullable=False)
    processing_error: Mapped[str] = mapped_column(Text, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ingested_by: Mapped[str] = mapped_column(String(64), nullable=True)
    retention_expires_at: Mapped[date] = mapped_column(Date, nullable=True)

    pages: Mapped[list] = relationship(
        "DocumentPage", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentPage(Base, DealScoped):
    """One row per page — the anchor every citation points at."""

    __tablename__ = "document_page"

    page_uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(48), ForeignKey("esg_document_register.document_id"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=True)
    ocr_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    is_image_only: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[EsgDocumentRegister] = relationship(
        "EsgDocumentRegister", back_populates="pages"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_page"),
    )


class MetricCandidate(Base, DealScoped):
    """A value the extractor believes it found, pending human confirmation.

    Nothing reaches esg_metric_data from here without an explicit accept, so
    the analysis layer never silently consumes a machine guess.
    """

    __tablename__ = "metric_candidate"

    candidate_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    company_id: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=True)
    reporting_year: Mapped[int] = mapped_column(Integer, nullable=True)
    raw_value: Mapped[str] = mapped_column(String(128), nullable=True)
    value: Mapped[float] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(64), nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int] = mapped_column(Integer, nullable=True)
    match_rule: Mapped[str] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Pending", nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    promoted_record_id: Mapped[str] = mapped_column(String(48), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Accepted', 'Rejected', 'Superseded')",
            name="ck_candidate_status",
        ),
        Index("ix_candidate_review", "deal_id", "status"),
    )


# ════════════════════════════════════════════════════════════════════
#  ETL: mappings, load runs and quarantine
# ════════════════════════════════════════════════════════════════════

class IngestionRun(Base, DealScoped):
    __tablename__ = "ingestion_run"

    run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(48), index=True, nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=True)
    target_table: Mapped[str] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Running", nullable=False)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0)
    rows_quarantined: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    gate_report: Mapped[str] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(64), nullable=True)


class QuarantinedRow(Base, DealScoped):
    """A source row the validation gate refused, kept with its reasons so it
    can be corrected and replayed rather than silently dropped."""

    __tablename__ = "quarantined_row"

    quarantine_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Quarantined", nullable=False)
    resolved_by: Mapped[str] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    replayed_run_id: Mapped[str] = mapped_column(String(48), nullable=True)


class ColumnMapping(Base, DealScoped):
    __tablename__ = "column_mapping"

    mapping_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    source_column: Mapped[str] = mapped_column(String(255), nullable=False)
    target_table: Mapped[str] = mapped_column(String(64), nullable=True)
    target_column: Mapped[str] = mapped_column(String(64), nullable=True)
    transform: Mapped[str] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Review required", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


# ════════════════════════════════════════════════════════════════════
#  Defensible outputs: exposure runs, sign-off, information requests
# ════════════════════════════════════════════════════════════════════

class ExposureRun(Base, DealScoped):
    """A quantification pass, pinned to the methodology version that produced
    it so a number in a client report can always be reproduced."""

    __tablename__ = "exposure_run"

    exposure_run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    company_id: Mapped[str] = mapped_column(String(32), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    point_estimate_usd: Mapped[float] = mapped_column(Float, nullable=True)
    low_usd: Mapped[float] = mapped_column(Float, nullable=True)
    high_usd: Mapped[float] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[str] = mapped_column(String(16), nullable=True)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=True)
    sensitivity_json: Mapped[str] = mapped_column(Text, nullable=True)
    basis: Mapped[str] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)


class InformationRequest(Base, DealScoped):
    """Deal-team IR tracker: what we asked the target for, and what came back."""

    __tablename__ = "information_request"

    ir_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reference: Mapped[str] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=True)
    linked_requirement_id: Mapped[str] = mapped_column(String(48), nullable=True)
    linked_finding_id: Mapped[str] = mapped_column(String(48), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Open", nullable=False)
    raised_by: Mapped[str] = mapped_column(String(64), nullable=True)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    due_date: Mapped[date] = mapped_column(Date, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    response_document_id: Mapped[str] = mapped_column(String(48), nullable=True)
    closed_by: Mapped[str] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class ReportSignoff(Base, DealScoped):
    """Partner sign-off gate. A report is only releasable once every required
    role has signed the exact content hash being released."""

    __tablename__ = "report_signoff"

    signoff_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    report_kind: Mapped[str] = mapped_column(String(64), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    signed_by: Mapped[str] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("report_id", "required_role", name="uq_signoff_role"),
        CheckConstraint(
            "decision IS NULL OR decision IN ('Approved', 'Rejected')",
            name="ck_signoff_decision",
        ),
    )


class ErasureRequest(Base):
    """DPDP / GDPR data-subject request against the platform's own PII."""

    __tablename__ = "erasure_request"

    request_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    subject_email_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    basis: Mapped[str] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Received", nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    outcome_json: Mapped[str] = mapped_column(Text, nullable=True)


DEAL_SCOPED_TABLES = tuple(
    m.__tablename__ for m in Base.__subclasses__() if issubclass(m, DealScoped)
)
