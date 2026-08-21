---
title: ESG Due Diligence Platform
emoji: 🌿
colorFrom: gray
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: AI-assisted ESG due diligence for M&A, with page-level evidence
---

# ESG Due Diligence Platform

Agentic ESG due diligence for M&A: ingest a target's data and documents, assess
them against regulatory frameworks, benchmark, quantify exposure, and produce a
red-flag report where every figure traces back to the page it came from.

> **Demo deployments are not for confidential data.** On Hugging Face Spaces the
> database lives in the container filesystem and is destroyed on rebuild or
> sleep. Real engagements need managed Postgres and the controls in
> [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Running locally

```bash
pip install -r requirements.txt
export ESG_DATA_KEYS="dev:$(python -m esg.db.crypto --generate)"
export ESG_ACTIVE_KEY_ID=dev
python -m alembic upgrade head
python -m esg.cli bootstrap-admin --email you@example.com --username you
streamlit run app.py
```

Accounts are provisioned, never self-created:

```bash
python -m esg.cli invite --email colleague@example.com --role Analyst --as you
python -m esg.cli grant --deal D001 --user <user_id> --level Editor --as you
```

## Architecture

```
esg/
  db/          SQLAlchemy models, migrations, deal-scope enforcement, field encryption
  etl/         validation gate, canonical-table loader, quarantine, transforms
  documents/   PDF/DOCX ingestion, page store, metric extraction, promotion
  methodology/ exposure quantification, versioned and review-gated
  benchmarks/  peer provenance rules
  assurance/   greenwashing reconciliation checks
  frameworks/  effective-dated requirement packs
  deal/        information requests, sign-off, red-flag report export
  privacy/     retention, subject access, erasure
  security/    provisioning, RBAC, hash-chained audit log
app.py         Streamlit entrypoint
views/         Streamlit pages
utils/         legacy analysis agents (being migrated onto esg.db.repository)
```

Two properties are worth knowing before changing anything:

- **Deal isolation is enforced in the session**, not at call sites. A query
  touching deal-scoped data with no principal bound fails closed. Aggregate
  forms that hide the entity in a subquery (`Query.count()`) raise rather than
  return unfiltered rows — use `esg.db.repository`.
- **Nothing machine-read reaches the analysis tables.** Document extraction
  produces candidates; a human accept writes the value with its document id and
  page number.

## What this tool will not do

- Present an uncalibrated exposure estimate as a single number. The judgement
  model returns a range and is labelled indicative. See
  [docs/METHODOLOGY.md](docs/METHODOLOGY.md).
- Export a report citing illustrative peer data. The bundled peer set is
  synthetic and refused for client deliverables.
- Claim complete framework coverage. Requirement packs are partial extracts and
  declare their own completeness.
- Treat a scanned page as empty. Without an OCR backend it is flagged for
  manual review.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

150 tests covering deal isolation, provisioning, the audit chain, the ETL gate,
document extraction and citations, exposure methodology, benchmark provenance,
greenwashing checks and report sign-off.
