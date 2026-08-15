"""
Scope 3 and supply-chain depth.

For most acquisition targets in services and light manufacturing, Scope 3 is
the large majority of the footprint, so a diligence exercise that stops at
Scope 1 and 2 has looked at the small part. This module quantifies the value
chain from supplier data and — importantly — reports how much of it is
*measured* versus *estimated from spend*, because a spend-derived figure carries
a very different weight in a negotiation.

The GHG Protocol's fifteen categories are named so gaps are explicit: an
unreported category is a stated gap, not a silent zero.
"""

from sqlalchemy import select

from esg.db.models import SupplierEsgAssessment, SupplierMaster

# GHG Protocol Scope 3 categories.
CATEGORIES = {
    1: "Purchased goods and services",
    2: "Capital goods",
    3: "Fuel- and energy-related activities",
    4: "Upstream transportation and distribution",
    5: "Waste generated in operations",
    6: "Business travel",
    7: "Employee commuting",
    8: "Upstream leased assets",
    9: "Downstream transportation and distribution",
    10: "Processing of sold products",
    11: "Use of sold products",
    12: "End-of-life treatment of sold products",
    13: "Downstream leased assets",
    14: "Franchises",
    15: "Investments",
}

# Categories usually material for the sectors this tool is aimed at. Used to
# decide which gaps matter, not to fabricate values.
SECTOR_MATERIAL_CATEGORIES = {
    "IT Services & Consulting": (1, 2, 6, 7, 11),
    "IT Services": (1, 2, 6, 7, 11),
    "Software": (1, 2, 6, 7, 11),
    "Manufacturing": (1, 2, 3, 4, 5, 9, 11, 12),
    "Retail": (1, 4, 9, 11, 12),
    "Financial Services": (1, 6, 15),
}

MEASURED = "measured"
ESTIMATED_SPEND = "spend_estimated"
ESTIMATED_AVERAGE = "average_data"

_BASIS_QUALITY = {MEASURED: 1.0, ESTIMATED_AVERAGE: 0.5, ESTIMATED_SPEND: 0.3}


def material_categories(industry):
    for key, categories in SECTOR_MATERIAL_CATEGORIES.items():
        if industry and key.lower() in industry.lower():
            return categories
    return tuple(CATEGORIES)


def inventory(session, company_id, industry=None):
    """Scope 3 inventory with data-quality weighting and named gaps."""
    assessments = session.execute(
        select(SupplierEsgAssessment).where(
            SupplierEsgAssessment.company_id == company_id
        )
    ).scalars().all()

    by_category = {}
    for assessment in assessments:
        if assessment.scope3_emissions_tco2e is None:
            continue
        try:
            category = int(assessment.scope3_category)
        except (TypeError, ValueError):
            category = None
        if category not in CATEGORIES:
            continue
        entry = by_category.setdefault(category, {
            "category": category,
            "category_name": CATEGORIES[category],
            "tco2e": 0.0,
            "supplier_count": 0,
            "bases": {},
            "tco2e_by_basis": {},
        })
        entry["tco2e"] += assessment.scope3_emissions_tco2e
        entry["supplier_count"] += 1
        basis = assessment.emissions_basis or ESTIMATED_SPEND
        entry["bases"][basis] = entry["bases"].get(basis, 0) + 1
        # Weight by emissions, not by supplier count. One spend-estimated
        # supplier can carry most of a category's tonnage, so counting heads
        # would overstate how much of the footprint is actually measured.
        entry["tco2e_by_basis"][basis] = (
            entry["tco2e_by_basis"].get(basis, 0.0) + assessment.scope3_emissions_tco2e
        )

    for entry in by_category.values():
        tonnes = entry["tco2e"] or 1.0
        entry["data_quality"] = round(
            sum(_BASIS_QUALITY.get(basis, 0.3) * amount
                for basis, amount in entry["tco2e_by_basis"].items()) / tonnes, 3
        )
        entry["measured_tco2e"] = round(entry["tco2e_by_basis"].get(MEASURED, 0.0), 2)
        entry["measured_share"] = round(
            entry["tco2e_by_basis"].get(MEASURED, 0.0) / tonnes, 3
        )

    expected = material_categories(industry)
    gaps = [
        {"category": category, "category_name": CATEGORIES[category],
         "status": "not reported",
         "why_it_matters": (
             f"Category {category} is typically material for {industry or 'this sector'}; "
             "its absence is a gap in the inventory, not a zero."
         )}
        for category in expected if category not in by_category
    ]

    total_tco2e = sum(e["tco2e"] for e in by_category.values())
    measured_tco2e = sum(e["measured_tco2e"] for e in by_category.values())

    return {
        "company_id": company_id,
        "industry": industry,
        "total_tco2e": round(total_tco2e, 2),
        "measured_tco2e": round(measured_tco2e, 2),
        "measured_share": round(measured_tco2e / total_tco2e, 3) if total_tco2e else None,
        "categories": sorted(by_category.values(), key=lambda e: -e["tco2e"]),
        "categories_reported": sorted(by_category),
        "material_categories_expected": list(expected),
        "gaps": gaps,
        "completeness": round(
            len([c for c in expected if c in by_category]) / len(expected), 3
        ) if expected else None,
        "caveat": (
            "Spend-estimated emissions dominate most Scope 3 inventories and carry "
            "wide uncertainty. Weight negotiation positions by measured_share, not "
            "by the headline total."
        ),
    }


def supplier_concentration(session, company_id, top_n=5):
    """Spend and ESG risk concentration among the largest suppliers.

    Concentration matters in diligence because a single critical supplier with a
    human-rights finding is a different risk from the same finding spread thinly.
    """
    assessments = session.execute(
        select(SupplierEsgAssessment).where(
            SupplierEsgAssessment.company_id == company_id
        )
    ).scalars().all()
    if not assessments:
        return {"suppliers_assessed": 0, "top_suppliers": [], "concentration_pct": None}

    suppliers = {
        s.supplier_id: s for s in session.execute(select(SupplierMaster)).scalars()
    }

    rows = []
    for assessment in assessments:
        supplier = suppliers.get(assessment.supplier_id)
        rows.append({
            "supplier_id": assessment.supplier_id,
            "supplier_name": supplier.supplier_name if supplier else assessment.supplier_id,
            "country": supplier.country if supplier else None,
            "tier": supplier.tier if supplier else None,
            "annual_spend": (supplier.annual_spend or 0) if supplier else 0,
            "criticality": supplier.criticality if supplier else None,
            "overall_esg_score": assessment.overall_esg_score,
            "human_rights_risk": assessment.human_rights_risk,
            "audit_status": assessment.audit_status,
            "corrective_action_status": assessment.corrective_action_status,
        })

    total_spend = sum(r["annual_spend"] for r in rows)
    top = sorted(rows, key=lambda r: -r["annual_spend"])[:top_n]
    top_spend = sum(r["annual_spend"] for r in top)

    high_risk = [r for r in rows
                 if (r["human_rights_risk"] or "").lower() in {"high", "critical"}]
    unaudited_critical = [
        r for r in rows
        if (r["criticality"] or "").lower() in {"high", "critical"}
        and (r["audit_status"] or "").lower() not in {"completed", "passed"}
    ]

    return {
        "suppliers_assessed": len(rows),
        "total_spend": total_spend,
        "top_suppliers": top,
        "concentration_pct": round(top_spend / total_spend * 100, 1) if total_spend else None,
        "high_human_rights_risk": high_risk,
        "critical_unaudited": unaudited_critical,
        "findings": _concentration_findings(rows, top, total_spend, high_risk,
                                           unaudited_critical),
    }


def _concentration_findings(rows, top, total_spend, high_risk, unaudited_critical):
    findings = []
    if total_spend and (sum(r["annual_spend"] for r in top) / total_spend) > 0.6:
        findings.append({
            "severity": "Medium",
            "finding": (
                f"{len(top)} suppliers account for "
                f"{sum(r['annual_spend'] for r in top) / total_spend * 100:.0f}% of "
                "assessed spend."
            ),
            "why_it_matters": ("Concentrated spend means a single supplier's ESG "
                              "failure transmits directly to the target."),
        })
    for row in high_risk:
        findings.append({
            "severity": "High",
            "finding": (f"{row['supplier_name']} ({row['country'] or 'unknown'}) is "
                        f"rated {row['human_rights_risk']} human-rights risk."),
            "why_it_matters": ("Human-rights findings in the supply chain carry "
                              "reputational and, in some jurisdictions, legal "
                              "liability for the acquirer."),
        })
    for row in unaudited_critical:
        findings.append({
            "severity": "Medium",
            "finding": (f"{row['supplier_name']} is critical but its audit status is "
                        f"{row['audit_status'] or 'not recorded'}."),
            "why_it_matters": "A critical supplier without a completed audit is an "
                              "unquantified exposure.",
        })
    return findings
