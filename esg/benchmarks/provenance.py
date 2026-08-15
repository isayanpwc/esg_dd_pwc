"""
Benchmark provenance — what the comparators actually are.

The dataset shipped with the tool is synthetic. Every company in it is
invented (Novabyte Technologies, Silverline Softworks, Helvetia Digital),
which is fine for a demo and misleading in a deal room: a percentile against
fictional peers is not a percentile.

Provenance is therefore a required column, and the rules here are enforced
rather than documented:

* `licensed`          — a commercial dataset under contract. Publishable.
* `public_disclosure` — figures read from named public reports, with citation.
                        Publishable with the source named.
* `illustrative`      — synthetic or demo. Never publishable, and any
                        statistic derived from it is labelled and, for report
                        export, refused.

A mixed cohort takes the weakest provenance in it, because one synthetic peer
contaminates the whole comparison.
"""

from sqlalchemy import select

from esg.db.models import PeerBenchmarkData

LICENSED = "licensed"
PUBLIC = "public_disclosure"
ILLUSTRATIVE = "illustrative"

_RANK = {LICENSED: 3, PUBLIC: 2, ILLUSTRATIVE: 1}

PUBLISHABLE = frozenset({LICENSED, PUBLIC})


class BenchmarkProvenanceError(RuntimeError):
    """Raised when illustrative comparators would reach a client deliverable."""


LABELS = {
    LICENSED: {
        "badge": "Licensed peer data",
        "tone": "ok",
        "detail": "Commercial dataset under licence. Suitable for client reporting.",
    },
    PUBLIC: {
        "badge": "Public disclosures",
        "tone": "ok",
        "detail": ("Compiled from named public reports. Cite the source alongside "
                   "any figure."),
    },
    ILLUSTRATIVE: {
        "badge": "ILLUSTRATIVE — not real peers",
        "tone": "warning",
        "detail": ("Synthetic demonstration data. Percentiles and rankings derived "
                   "from it are not evidence and must not be shown to a client."),
    },
}


def weakest(provenances):
    """The provenance a mixed cohort inherits."""
    present = [p for p in provenances if p in _RANK]
    if not present:
        return ILLUSTRATIVE
    return min(present, key=lambda p: _RANK[p])


def cohort_provenance(session, metric_code, industry=None, country=None,
                      reporting_year=None):
    """Provenance and composition of the peer set a comparison would use."""
    stmt = select(PeerBenchmarkData).where(PeerBenchmarkData.metric_code == metric_code)
    if industry:
        stmt = stmt.where(PeerBenchmarkData.industry == industry)
    if country:
        stmt = stmt.where(PeerBenchmarkData.country == country)
    if reporting_year:
        stmt = stmt.where(PeerBenchmarkData.reporting_year == reporting_year)

    rows = session.execute(stmt).scalars().all()
    provenance = weakest([r.provenance for r in rows])
    counts = {}
    for row in rows:
        counts[row.provenance] = counts.get(row.provenance, 0) + 1

    return {
        "metric_code": metric_code,
        "peer_count": len({r.peer_company_name for r in rows}),
        "observation_count": len(rows),
        "provenance": provenance,
        "composition": counts,
        "publishable": provenance in PUBLISHABLE and bool(rows),
        "label": LABELS[provenance],
        "sources": sorted({r.source_name for r in rows if r.source_name})[:10],
        "dataset_versions": sorted({r.dataset_version for r in rows if r.dataset_version}),
    }


def annotate(result, cohort):
    """Attach provenance to a benchmark result so the UI cannot omit it."""
    enriched = dict(result)
    enriched["provenance"] = cohort["provenance"]
    enriched["provenance_label"] = cohort["label"]["badge"]
    enriched["provenance_detail"] = cohort["label"]["detail"]
    enriched["publishable"] = cohort["publishable"]
    if not cohort["publishable"]:
        enriched["display_suffix"] = " (illustrative data)"
    return enriched


def require_publishable(cohort, context="this deliverable"):
    """Gate for report export."""
    if not cohort["publishable"]:
        raise BenchmarkProvenanceError(
            f"The peer cohort for {cohort['metric_code']} is "
            f"{cohort['provenance']} and cannot be used in {context}. "
            f"Composition: {cohort['composition']}. Load a licensed peer dataset "
            "or compile figures from named public disclosures first."
        )
    return cohort


def sufficiency(cohort, min_for_quartile=10, min_for_directional=5):
    """Whether the cohort is large enough for the claim being made.

    A percentile against four peers is arithmetic, not evidence.
    """
    count = cohort["peer_count"]
    if count >= min_for_quartile:
        return {"level": "quartile", "peer_count": count,
                "claim": "Quartile and percentile positioning supported."}
    if count >= min_for_directional:
        return {"level": "directional", "peer_count": count,
                "claim": ("Directional comparison only — too few peers for reliable "
                          "percentiles.")}
    return {"level": "insufficient", "peer_count": count,
            "claim": ("Insufficient peers for any comparative claim. Report the "
                      "target's absolute values instead.")}
