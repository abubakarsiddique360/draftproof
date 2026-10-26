# Development

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install
```

## Commands

| Command | What it does |
| --- | --- |
| `make lint` | `ruff check .` |
| `make fmt` | `ruff format .` |
| `make typecheck` | `mypy` (strict, `src/draftproof`) |
| `make test` | `pytest` |
| `make cov` | coverage report, fails under 80% |
| `make web-test` | `node --test` on the studio modules |
| `make docs` | `mkdocs build --strict` |
| `make check` | lint + typecheck + tests + web tests |
| `make demo` | offline end-to-end run |
| `make eval` | golden-case evaluation |

## Test strategy

| Layer | Location | Focus |
| --- | --- | --- |
| Unit | `tests/unit/` | Models, config, storage, providers, research, verification, quality, export, parsing, security |
| Integration | `tests/integration/` | Full pipeline, resume, cancellation, review flow, HTTP API, CLI |
| Front-end | `src/draftproof/web/test/` | Markdown sanitiser, formatting, state reducer, SSE parser |

Principles:

- **No network in tests.** `httpx.MockTransport` stands in for providers and fetchers; the mock provider and bundled corpus drive the pipeline.
- **Assert behaviour, not implementation.** Tests exercise public seams (services, routes, CLI commands, pure helpers).
- **Cover the failure paths.** Unreachable citations, weak support, blocked domains, SSRF attempts, injection payloads, malformed model JSON, budget exhaustion, invalid transitions.

```bash
python -m pytest -q
python -m pytest tests/unit/test_verifier.py -q
python -m pytest -k "sanitizer or ssrf" -q
node --test src/draftproof/web/test/*.test.js
```

## Adding a stage

```python
from draftproof.pipeline.executor import Stage, default_stages

stages = [*default_stages(), Stage("notify", notify_stage)]
```

Emit events through `context.sink` so every client sees progress, and persist through `context.repo` so resume stays correct.

## Adding a provider

Implement `Provider.complete`, map transport errors to `TransientProviderError`, add a preset, and test with `httpx.MockTransport`.

## Front-end

The studio has no build step. Modules live in `src/draftproof/web/js/` and are served directly. Pure modules (`format`, `markdown`, `store`, `sse`) are covered by `node --test`; DOM wiring lives in `app.js` and `ui.js`.

CSP is enabled for the studio shell (`default-src 'self'`), so no inline scripts or external fonts are allowed. Markdown is rendered with a small safe renderer; the exported HTML is sanitised again on the server.

## Release checklist

1. Update `CHANGELOG.md` (move **Unreleased** items under the new version).
2. Bump `__version__` in `src/draftproof/__init__.py`.
3. `make check && make docs && make build`.
4. Verify the wheel contains the web assets, migrations and corpus:
   `python -c "import zipfile;print([n for n in zipfile.ZipFile('dist/draftproof-<v>-py3-none-any.whl').namelist() if 'web/' in n][:5])"`
5. Tag and push: `git tag vX.Y.Z && git push origin main --tags`.
