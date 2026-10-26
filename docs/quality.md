# Quality rubric

DraftProof does not ask a model whether the article is good. It computes eight measurements and applies explicit gates. The report is reproducible: identical text always produces identical scores.

## Metrics

| Key | Weight | Value | Score function |
| --- | ---: | --- | --- |
| `structure` | 0.18 | 0–100 checklist | Headings (20), substance (15), lists/code (15), no placeholders (10), balanced fences (15), heading depth (10), section count (5), intro/outro framing (10) |
| `readability` | 0.14 | Flesch reading ease | 100 inside the target band (default 40–65); −2.5 per point outside |
| `citation_coverage` | 0.18 | % verified claims | Verified ÷ total, or 0 when sources are required and no claims exist |
| `repetition` | 0.10 | % duplicated | 100 × (1 − ratio ÷ 0.15), using cross-section duplicate 12-grams and duplicate sentences |
| `code_validity` | 0.10 | % parsing blocks | `ast.parse` (Python), `json.loads` (JSON), bracket balance otherwise; 100 when there is no code |
| `word_budget` | 0.12 | word count | 100 × (1 − |actual − target| ÷ target ÷ 0.35) |
| `seo` | 0.08 | 0–100 checklist | Title length (30), description length (30), tags (10), topic keyword in headings (30) |
| `hedging` | 0.10 | hedges per 100 words | 100 × (1 − density ÷ 2.0) |

`prose_only()` strips fenced code and heading lines before readability, repetition and word counting, so a code-heavy article is judged on its prose.

## Gates

A run is publishable only when every applicable gate passes:

| Gate | Minimum | Condition |
| --- | ---: | --- |
| `score` | 75 | always |
| `structure` | 70 | always |
| `word_budget` | 60 | always |
| `repetition` | 60 | always |
| `code_validity` | 90 | always |
| `readability` | 40 | always |
| `citation_coverage` | 70 | only when the brief requires sources |

Failing gates are listed in `quality.failed_gates` and shown as a red badge in the studio, in the Markdown appendix and in the manifest.

## Issues and directives

Every failing metric becomes an `Issue`:

```json
{
  "code": "citation_coverage_gate",
  "message": "Factual claims are not supported by verified evidence. (0.0 < 70.0)",
  "severity": "high",
  "directive": "Attach an evidence id to every factual claim and delete claims that no source supports."
}
```

Plus a per-section issue whenever fewer than 60% of that section's claims are verified:

```json
{
  "code": "section_grounding",
  "message": "Section 'Failure modes' has 1/4 verified claims.",
  "severity": "high",
  "section_id": "s5",
  "directive": "Rewrite this section so every factual sentence cites a verified source, or remove the unsupported claims (s5c2, s5c3)."
}
```

The revision stage consumes these directives directly, and `failing_section_ids()` decides *which* sections are re-drafted, so a failing citation gate never triggers a full rewrite.

## Custom rubrics

```yaml
# rubric.yml
weights:
  structure: 0.20
  citation_coverage: 0.25
  readability: 0.15
  repetition: 0.10
  code_validity: 0.10
  word_budget: 0.10
  seo: 0.05
  hedging: 0.05
gates:
  - key: score
    minimum: 82
  - key: citation_coverage
    minimum: 90
    condition: sources_required
flesch_target: [35, 60]
```

```python
from draftproof.pipeline.service import RunService

service = RunService.build(rubric_path="rubric.yml")
```

Unknown metric keys are rejected at load time so a typo cannot silently disable a metric. `GET /api/v1/rubric` exposes the active weights and gates to the UI.

## Using the rubric as a regression harness

`draftproof eval` runs the golden cases in `evals/cases/` and checks explicit expectations:

```json
{
  "expect": {
    "min_score": 80,
    "gates_passed": true,
    "min_sections": 4,
    "min_verified_claims": 3,
    "max_cost_usd": 0.0,
    "required_artifacts": ["markdown", "html", "manifest"]
  }
}
```

This turns prompt and rubric changes into measurable diffs: if a prompt edit drops the mean score or breaks a gate, CI fails.
