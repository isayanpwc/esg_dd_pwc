# Methodology and its limits

Written to be read by someone challenging a number in this tool's output.

## Exposure quantification

Version: `2026.08-draft` (`esg.methodology.exposure.METHODOLOGY_VERSION`).
Every `exposure_run` row records the version that produced it, so any figure in
any historical report can be reproduced.

### Basis hierarchy

Methods are preferred by evidence quality, not by the size of the number they
produce.

| Method | Basis | Presented as | Source of the amount |
|---|---|---|---|
| `levied_penalty` | observed | Quantified | Amount in a regulator's order, FX-converted at a dated reference rate |
| `booked_provision` | observed | Quantified | The target's own audited provision |
| `quoted_remediation` | observed | Quantified (range) | A quoted or engineered cost to remediate |
| `expected_value` | **uncalibrated** | **Indicative only** | Judgement parameters — see below |

### The expected-value model, and why it gives no point estimate

```
exposure ∈ [ revenue × p_low × s_low , revenue × p_high × s_high ]
```

where `p` is the probability the exposure crystallises and `s` its impact as a
share of revenue. Both are **placeholders pending empirical calibration**:

- `CRYSTALLISATION_PROBABILITY` — requires calibration against PwC's realised
  outcomes for comparable ESG findings. Not derived from published research.
- `IMPACT_AS_REVENUE_SHARE` — requires calibration against observed remediation,
  fine and business-interruption costs by sector and finding category.

Because the parameters are uncalibrated, this method:

1. returns `point_estimate_usd = None` — the code cannot emit a single number;
2. is labelled `indicative` everywhere it is displayed;
3. is excluded from the quantified total in a report;
4. carries a sensitivity table showing which driver the answer depends on.

**This is the honest position, not a placeholder for one.** Producing a precise
figure from uncalibrated judgement inputs would misrepresent what is known. If
the practice calibrates these parameters, replace the constants, record the
calibration source in `PARAMETER_PROVENANCE`, bump
`METHODOLOGY_VERSION`, and update the golden tests in
`tests/test_credibility.py` deliberately.

### Review gate

No exposure enters a client deliverable until a Manager has reviewed the
specific run (`exposure.require_review`). Admin cannot review or sign — platform
administration is not professional responsibility.

## Benchmarks

Provenance is a required column with three values:

- `licensed` — commercial dataset under contract. Publishable.
- `public_disclosure` — compiled from named public reports. Publishable with the
  source cited.
- `illustrative` — synthetic. **Never publishable.**

**The dataset shipped with this repository is `illustrative`.** Every company in
it is invented. Report export refuses it, and one illustrative peer downgrades
the entire cohort, because a percentile is only as real as its weakest
comparator.

Cohort size governs the claim: 10+ peers for quartiles, 5–9 for directional
comparison only, fewer than 5 for no comparative claim at all.

## Framework coverage

Requirement packs are **partial extracts** with source citations, not complete
corpora, and each declares its own completeness:

| Framework | Requirements in pack | Estimated full scope |
|---|---|---|
| SEBI BRSR Core (`2023-core`) | 22 | ~1,000 data points |
| EU CSRD / ESRS Set 1 (`esrs-set1-2024`) | 20 | ~1,100 data points |

`registry.coverage_report()` surfaces this so the interface states what is
covered instead of implying the whole framework. **These packs cannot support a
statutory completeness assertion.** Completing them requires the authoritative
standard texts and, for CSRD, the entity's own double-materiality assessment.

Requirements are effective-dated. Assessing FY2022 against a ruleset effective
from 2023 raises rather than scoring the target on rules that did not yet exist.

## Greenwashing checks

Four checks that point at specific disagreeing numbers rather than emitting a
score:

1. **Reported vs operational** — group total against the sum of facility rows,
   with the facilities that have no data named. Tolerance 5%.
2. **Restatements** — prior-year revisions above 10%, flagged more severely when
   the revision flatters the trend (e.g. a base year raised for a
   lower-is-better metric).
3. **Assurance gaps** — metrics flagged audited where no assurance on file
   covers them.
4. **Target divergence** — claimed progress against what the metric data implies.

Each finding carries the document and page its values came from. None of them
concludes that a company is greenwashing; they identify numbers that do not
agree, for a human to resolve.

## Scope 3

Fifteen GHG Protocol categories, with sector materiality deciding which absences
matter. Two properties matter in a negotiation:

- `measured_share` is weighted **by emissions, not by supplier count** — one
  spend-estimated supplier can carry most of a category's tonnage.
- An unreported category is a **named gap, not a zero**.

Weight positions by `measured_share`; spend-derived estimates carry wide
uncertainty.

## Document extraction

Rule-based and inspectable by design, so behaviour is reproducible when a figure
is challenged months later. Confidence is a sum of checkable terms (unit match,
distance from the label, pattern specificity), not a learned weight.

Extraction produces **candidates**. Nothing enters `esg_metric_data` without a
human accept, which writes the document id and page number alongside the value.
A reviewer may correct the reading; the original machine value stays on the
candidate.

Known limits:

- Table-heavy layouts where a label and its value are separated by more than
  ~140 characters may be missed. A missed figure is a gap, which is safer than a
  wrong one.
- Multi-year comparison tables can attribute a value to the wrong year where no
  year appears near the match; the reviewer sees the snippet and can correct it.
- Scanned pages need an OCR backend. Without one they are flagged `NeedsOcr`,
  never treated as empty.
