# Sample data — SYNTHETIC, for development/testing only

Every file in this directory is **fabricated** by `scripts/generate_sample_data.py`
(seeded, reproducible). All companies, people, suppliers, documents, metrics,
controversies, penalties and findings are **fictional**. Any resemblance to real
organisations is coincidental.

**Do not:**
- present any figure here as reflecting a real company,
- use it for actual investment or diligence decisions,
- treat the numbers as having analytical meaning — they come from formulas, not measurement.

**Purpose:** exercise the ESG Due Diligence Assistant pipeline (extraction →
compliance → benchmarking → risk) and the Streamlit app against a realistically
shaped, foreign-key-consistent dataset with deliberately planted issues
(e.g. a data breach, incomplete Scope 3, an expired certification) so the agents
have something to find.

**Contents:** 24 CSV tables across 4 fictional IT-sector M&A deals (2015–2024).
See `docs/data-model.md` for the full data dictionary.

**Regenerate:** `python scripts/generate_sample_data.py`

Real engagement data comes from the client VDR plus the public/licensed sources
described in the project docs — never from this folder.
