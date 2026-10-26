# Contributing to DraftProof

Thanks for taking the time to contribute. This document explains how the project is structured, how to run it locally, and what a good change looks like.

## Getting started

```bash
git clone https://github.com/abubakarsiddique360/draftproof.git
cd draftproof
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install                 # optional but recommended
```

Verify your environment:

```bash
draftproof doctor
make check
```

## Project conventions

- **Typed everywhere.** `mypy --strict` runs in CI; public functions and helpers carry annotations.
- **Small, single-purpose modules.** Storage, providers, research, quality, export, pipeline and the API are separate packages.
- **Deterministic tests.** No network in the default suite. The `mock` provider and the bundled corpus exist so the whole pipeline is testable offline.
- **No secrets in the repo.** Never commit `.env`, keys or generated `data/`.
- **Documented behaviour changes.** Update `README.md`, `docs/` and `CHANGELOG.md` when a user-visible behaviour changes.

## Quality gates

```bash
make lint        # ruff check
make fmt         # ruff format
make typecheck   # mypy --strict
make test        # pytest
make web-test    # node --test on the studio modules
make docs        # mkdocs build --strict
```

Coverage must stay at or above 80% (`make cov`).

## Adding a provider

1. Implement the `Provider` protocol from `src/draftproof/providers/base.py`.
2. Add a preset to `providers/pricing.py` (`kind`, `base_url`, `default_model`, `api_key_env`).
3. Map HTTP failures onto `TransientProviderError` or `ProviderError`.
4. Add unit tests using `httpx.MockTransport` — no live calls.
5. Document the provider in `README.md` and `docs/configuration.md`.

## Adding a quality metric

1. Add the measurement in `quality/metrics.py` (pure function, no I/O).
2. Add the key and weight to `DEFAULT_WEIGHTS` in `quality/rubric.py`.
3. Add a gate in `DEFAULT_GATES` if the metric should block publishing.
4. Add an entry to `_GUIDANCE` in `quality/evaluator.py` with an actionable directive.
5. Add tests for the measurement and for the gate.

## Pull request checklist

- [ ] `make check` passes
- [ ] Tests cover the new behaviour (including failure paths)
- [ ] Public behaviour is documented
- [ ] `CHANGELOG.md` has an entry under **Unreleased**
- [ ] No secrets, generated artifacts or unrelated formatting churn

## Reporting bugs

Include the DraftProof version (`draftproof version`), the provider and retriever you used, the run id if applicable, and the relevant `events` from `GET /api/v1/runs/{id}/events`.
