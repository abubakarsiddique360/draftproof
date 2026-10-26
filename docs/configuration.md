# Configuration

Every setting is read from the environment (or a `.env` file) with the `DRAFTPROOF_` prefix. Nested behaviour is documented below; secrets are never returned by the API or written to the manifest.

## Provider routing

| Variable | Default | Description |
| --- | --- | --- |
| `DRAFTPROOF_PROVIDER` | `mock` | Primary provider: `mock`, `openai`, `groq`, `ollama`, `openrouter`, `anthropic` |
| `DRAFTPROOF_MODEL` | preset default | Overrides the model name for the primary provider |
| `DRAFTPROOF_FALLBACK_PROVIDERS` | — | Comma-separated names tried in order after the primary |
| `DRAFTPROOF_BASE_URL` | preset default | Custom endpoint for the primary provider |
| `DRAFTPROOF_API_KEY` | — | Primary provider key |
| `DRAFTPROOF_ANTHROPIC_API_KEY` | — | Claude key when the fallback chain includes Anthropic |
| `DRAFTPROOF_TEMPERATURE` | `0.25` | Sampling temperature (0–2) |
| `DRAFTPROOF_MAX_TOKENS` | `3000` | Upper bound for a single completion |
| `DRAFTPROOF_REQUEST_TIMEOUT` | `60` | HTTP timeout per provider call (seconds) |
| `DRAFTPROOF_MAX_RETRIES` | `2` | Retries per provider on transient errors |
| `DRAFTPROOF_CONCURRENCY` | `4` | Parallel writers / claim extractors |
| `DRAFTPROOF_SEED` | `7` | Deterministic seed for the mock provider |

### Provider presets

| Name | Base URL | Default model | Key env |
| --- | --- | --- | --- |
| `mock` | — | `mock-writer-1` | — |
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `groq` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `ollama` | `http://localhost:11434/v1` | `llama3.1:8b` | — (local) |
| `openrouter` | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` | `OPENROUTER_API_KEY` |
| `anthropic` | `https://api.anthropic.com` | `claude-3-5-sonnet-latest` | `ANTHROPIC_API_KEY` |

Local base URLs (`localhost`, `127.0.0.1`, `host.docker.internal`) do not require a key.

## Run policy

| Variable | Default | Description |
| --- | --- | --- |
| `DRAFTPROOF_MAX_COST_USD` | `1.0` | Hard per-run budget; `0` disables the ceiling |
| `DRAFTPROOF_MAX_REVISION_ATTEMPTS` | `2` | Bounded revision loop (0 disables revision) |
| `DRAFTPROOF_REVIEW_REQUIRED` | `false` | Finish in `awaiting_review` instead of `completed` |

## Research and verification

| Variable | Default | Description |
| --- | --- | --- |
| `DRAFTPROOF_RETRIEVER` | `local_corpus` | `local_corpus`, `tavily`, `none` |
| `DRAFTPROOF_TAVILY_API_KEY` | — | Required for the Tavily retriever |
| `DRAFTPROOF_SEARCH_ENDPOINT` | Tavily default | Point at a compatible search API |
| `DRAFTPROOF_VERIFICATION` | `auto` | `auto`, `live`, `corpus`, `off` |
| `DRAFTPROOF_VERIFICATION_MIN_OVERLAP` | `0.18` | Support threshold for a verified claim |
| `DRAFTPROOF_EVIDENCE_LIMIT` | `8` | Sources kept per run |
| `DRAFTPROOF_RESULTS_PER_QUERY` | `4` | Documents requested per query |
| `DRAFTPROOF_ALLOWED_DOMAINS` | — | Comma-separated allow list (subdomains included) |
| `DRAFTPROOF_BLOCKED_DOMAINS` | — | Comma-separated deny list |
| `DRAFTPROOF_FETCH_MAX_BYTES` | `200000` | Body cap for verification fetches |
| `DRAFTPROOF_FETCH_TIMEOUT` | `8` | Timeout for verification fetches |

`DRAFTPROOF_VERIFICATION=auto` resolves to `corpus` for the bundled retriever and `live` for Tavily.

## HTTP service

| Variable | Default | Description |
| --- | --- | --- |
| `DRAFTPROOF_SERVICE_API_KEY` | — | Enables `X-API-Key` auth on `/api/v1` |
| `DRAFTPROOF_RATE_LIMIT_PER_MINUTE` | `60` | Per-client token bucket (`0` disables) |
| `DRAFTPROOF_CORS_ORIGINS` | — | Comma-separated allowed origins |
| `DRAFTPROOF_MAX_BODY_BYTES` | `262144` | Request body cap |

## Storage and logging

| Variable | Default | Description |
| --- | --- | --- |
| `DRAFTPROOF_DATA_DIR` | `data` | Database root (`draftproof.db`) and `artifacts/` |
| `DRAFTPROOF_DATABASE_PATH` | `data/draftproof.db` | Explicit SQLite file path |
| `DRAFTPROOF_ENV` | `dev` | `dev`, `test` or `prod` |
| `DRAFTPROOF_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

## Lists in the environment

List values accept either a JSON array or a comma-separated string:

```bash
DRAFTPROOF_FALLBACK_PROVIDERS="groq,openai"
DRAFTPROOF_ALLOWED_DOMAINS='["docs.python.org", "developer.mozilla.org"]'
```

## Precedence

1. Explicit constructor arguments (`Settings(...)`, CLI flags).
2. Process environment.
3. `.env` file in the working directory.
4. Defaults.

`draftproof doctor` prints the effective provider chain, storage path, retrieval and verification modes, and whether each provider is usable.
