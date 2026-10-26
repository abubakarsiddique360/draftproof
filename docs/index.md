# DraftProof

DraftProof turns a brief into a published, *verified* article. It plans, researches, drafts in parallel, extracts claims, checks those claims against their cited sources, scores the result against a deterministic rubric, revises only the sections that fail, and publishes artifacts with a provenance manifest.

Two ideas shape the whole project:

1. **Citations are checked, not requested.** A prompt that says "cite your sources" produces plausible-looking links. DraftProof resolves the link, reads the source and measures whether the claim is actually supported.
2. **Quality is measured, not asserted.** A model grading its own output is not a quality gate. DraftProof uses metrics it can compute every time, with explicit gates and actionable fix directives.

## Install and run

```bash
pip install -e ".[dev]"
draftproof demo          # offline, deterministic, no API key
draftproof serve         # studio UI on http://127.0.0.1:8000
```

## What one run produces

```text
demo-output/
├── article.md          # front matter + body + sources + editorial report
├── article.html        # self-contained page with inline CSS
├── article.jsonld.json # schema.org Article
├── social.json         # X thread and LinkedIn copy
├── outline.json        # the plan the writer followed
├── quality.json        # every metric, gate and issue
└── manifest.json       # models, evidence, verdicts and artifact digests
```

## Next steps

- [Architecture](architecture.md) — how the packages fit together.
- [Pipeline](pipeline.md) — what each stage does and when it stops.
- [Verification](verification.md) — how a claim becomes "verified".
- [Quality rubric](quality.md) — what "publishable" means here.
- [Configuration](configuration.md) — every environment variable.
