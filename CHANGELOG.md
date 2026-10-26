# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-26

### Added

- Eight-stage publishing pipeline (brief, plan, research, draft, claims, verify, critique, revise, publish) with stage checkpoints, resume and cooperative cancellation.
- Deterministic claim verification against live HTTP sources or the bundled offline corpus, with per-claim confidence and machine-readable failure notes.
- Weighted quality rubric with eight metrics, configurable hard gates, automatic bounded revision and actionable fix directives.
- Provider gateway: OpenAI-compatible endpoints, Anthropic, and a deterministic `mock` provider with JSON-Schema synthesis for offline runs.
- Resilient routing with retries, exponential backoff, per-provider circuit breaking, fallback chains and a per-run USD budget.
- SSRF-safe URL policy and fetcher, prompt-injection quarantine, HTML allow-list sanitiser and path-safe artifact storage.
- SQLite storage with versioned migrations, a run repository, an event log for SSE replay and immutable artifact digests.
- FastAPI service with SSE streaming, API-key auth, rate limiting, body-size caps, security headers, health, meta, rubric and Prometheus metrics endpoints.
- Dependency-free studio UI: run list, live event stream, outline, per-section claim verdicts, quality dashboard, sources, artifacts and manifest.
- Publishing outputs: Markdown with front matter, self-contained HTML, JSON-LD, social pack, quality report, outline and provenance manifest.
- Typer CLI: `run`, `demo`, `serve`, `list`, `show`, `approve`, `export`, `doctor`, `eval`, `version`.
- Golden-case evaluation harness with expectations for score, gates, sections, verified claims, cost, duration and artifacts.
- Test suite (172 Python tests, 40 front-end module tests) at 88% coverage, `mypy --strict`, `ruff` and CI on Python 3.11–3.13.
- Documentation site, Docker image, compose file, issue/PR templates, CodeQL and Dependabot configuration.
