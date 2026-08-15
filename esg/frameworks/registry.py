"""
Versioned regulatory requirement library.

Two problems with the previous arrangement. First, size: ten requirement rows
covered twelve frameworks, while BRSR Core alone runs to roughly a thousand
data points and ESRS Set 1 to around eleven hundred — so "nine frameworks
simultaneously" was structurally true and substantively empty. Second, and more
dangerous for a deal: requirements had no effective dates, so an assessment of
FY2023 was scored against today's rules.

This module fixes the second problem and gives the first a shape to be filled.
Requirements are effective-dated; an assessment resolves the ruleset that was in
force on the date being assessed, and the resolved version is stamped onto the
assessment so the basis is reproducible.

On coverage: the seed packs under esg/frameworks/data are *partial extracts*
with source citations, not the complete corpora. Completing them is a content
task requiring the authoritative standard texts, and each pack declares its own
completeness so the UI can state what is actually covered rather than implying
the whole framework.
"""

import json
import os
import uuid
from datetime import date

from sqlalchemy import select

from esg.db.models import RegulationMaster, RegulatoryRequirement
from esg.security import audit

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class FrameworkError(RuntimeError):
    pass


class CoverageWarning(UserWarning):
    pass


def available_packs():
    if not os.path.isdir(DATA_DIR):
        return []
    # Skip macOS AppleDouble sidecars ("._name.json"), which are byte-for-byte
    # resource forks rather than JSON and appear on non-native filesystems.
    return sorted(
        f for f in os.listdir(DATA_DIR)
        if f.endswith(".json") and not f.startswith("._")
    )


def load_pack(path):
    with open(path, "r", encoding="utf-8") as handle:
        pack = json.load(handle)
    for key in ("regulation", "ruleset_version", "effective_from", "coverage", "requirements"):
        if key not in pack:
            raise FrameworkError(f"{os.path.basename(path)} is missing {key!r}")
    return pack


def _as_date(value):
    if value in (None, "", "null"):
        return None
    return date.fromisoformat(value)


def install_pack(session, path, actor_principal):
    """Load a requirement pack, superseding the previous version.

    Installing version N closes the open effective window of version N-1 on the
    day before N takes effect, so the two never both apply.
    """
    from esg.security import rbac

    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)

    pack = load_pack(path)
    regulation = pack["regulation"]
    effective_from = _as_date(pack["effective_from"])
    effective_to = _as_date(pack.get("effective_to"))

    existing_regulation = session.get(RegulationMaster, regulation["regulation_id"])
    if existing_regulation is None:
        session.add(RegulationMaster(
            regulation_id=regulation["regulation_id"],
            regulation_name=regulation["regulation_name"],
            jurisdiction=regulation.get("jurisdiction"),
            regulatory_body=regulation.get("regulatory_body"),
            effective_date=effective_from,
            applicable_industry=regulation.get("applicable_industry"),
            mandatory_flag=regulation.get("mandatory_flag"),
            regulation_version=pack["ruleset_version"],
            source_url=regulation.get("source_url"),
        ))
    else:
        existing_regulation.regulation_version = pack["ruleset_version"]

    # Close the previous version's window.
    superseded = session.execute(
        select(RegulatoryRequirement).where(
            RegulatoryRequirement.regulation_id == regulation["regulation_id"],
            RegulatoryRequirement.ruleset_version != pack["ruleset_version"],
            RegulatoryRequirement.effective_to.is_(None),
        )
    ).scalars().all()
    from datetime import timedelta

    for requirement in superseded:
        requirement.effective_to = effective_from - timedelta(days=1)

    installed = 0
    for item in pack["requirements"]:
        requirement_id = item.get("requirement_id") or (
            f"{regulation['regulation_id']}-{pack['ruleset_version']}-{item['requirement_code']}"
        )
        if session.get(RegulatoryRequirement, requirement_id) is not None:
            continue
        session.add(RegulatoryRequirement(
            requirement_id=requirement_id,
            regulation_id=regulation["regulation_id"],
            requirement_code=item["requirement_code"],
            requirement_name=item["requirement_name"],
            requirement_description=item.get("requirement_description"),
            required_metric_code=item.get("required_metric_code"),
            required_document=item.get("required_document"),
            mandatory_flag=item.get("mandatory_flag", "Yes"),
            compliance_frequency=item.get("compliance_frequency", "Annual"),
            disclosure_topic=item.get("disclosure_topic"),
            applies_to_industry=item.get("applies_to_industry"),
            effective_from=effective_from,
            effective_to=effective_to,
            ruleset_version=pack["ruleset_version"],
            source_citation=item.get("source_citation") or pack["coverage"].get("source"),
        ))
        installed += 1

    audit.record(
        session, actor_principal.username, "framework.pack_installed",
        entity_type="regulation_master", entity_id=regulation["regulation_id"],
        detail={"version": pack["ruleset_version"], "requirements": installed,
                "superseded": len(superseded),
                "completeness": pack["coverage"].get("completeness")},
    )
    session.flush()
    return {"regulation_id": regulation["regulation_id"],
            "version": pack["ruleset_version"],
            "installed": installed,
            "superseded": len(superseded),
            "coverage": pack["coverage"]}


def install_all(session, actor_principal):
    return [install_pack(session, os.path.join(DATA_DIR, name), actor_principal)
            for name in available_packs()]


def requirements_in_force(session, regulation_id, as_of, industry=None):
    """Requirements in force on `as_of` — the core of reproducible assessment."""
    stmt = select(RegulatoryRequirement).where(
        RegulatoryRequirement.regulation_id == regulation_id,
        RegulatoryRequirement.effective_from <= as_of,
    ).where(
        (RegulatoryRequirement.effective_to.is_(None))
        | (RegulatoryRequirement.effective_to >= as_of)
    )
    rows = session.execute(stmt.order_by(RegulatoryRequirement.requirement_code)).scalars().all()

    if industry:
        rows = [r for r in rows
                if not r.applies_to_industry
                or industry.lower() in r.applies_to_industry.lower()
                or r.applies_to_industry.lower() in ("all", "all industries")]
    return rows


def resolve_ruleset_version(session, regulation_id, as_of):
    rows = requirements_in_force(session, regulation_id, as_of)
    versions = {r.ruleset_version for r in rows if r.ruleset_version}
    if not versions:
        raise FrameworkError(
            f"No requirements for {regulation_id} were in force on {as_of}. "
            "Install the applicable requirement pack before assessing this period."
        )
    if len(versions) > 1:
        raise FrameworkError(
            f"{regulation_id} has overlapping rulesets in force on {as_of}: "
            f"{', '.join(sorted(versions))}. Effective windows must not overlap."
        )
    return versions.pop()


def coverage_report(session):
    """What is actually loaded, so the UI can stop implying full coverage."""
    regulations = session.execute(select(RegulationMaster)).scalars().all()
    packs = {}
    for name in available_packs():
        pack = load_pack(os.path.join(DATA_DIR, name))
        packs[pack["regulation"]["regulation_id"]] = pack["coverage"]

    report = []
    for regulation in regulations:
        loaded = session.execute(
            select(RegulatoryRequirement).where(
                RegulatoryRequirement.regulation_id == regulation.regulation_id
            )
        ).scalars().all()
        coverage = packs.get(regulation.regulation_id, {})
        estimated_total = coverage.get("estimated_total_datapoints")
        report.append({
            "regulation_id": regulation.regulation_id,
            "regulation_name": regulation.regulation_name,
            "version": regulation.regulation_version,
            "requirements_loaded": len(loaded),
            "estimated_total_datapoints": estimated_total,
            "completeness": coverage.get("completeness", "unknown"),
            "coverage_pct": (round(len(loaded) / estimated_total * 100, 1)
                             if estimated_total else None),
            "source": coverage.get("source"),
            "caveat": coverage.get("caveat"),
        })
    return sorted(report, key=lambda r: r["regulation_id"])
