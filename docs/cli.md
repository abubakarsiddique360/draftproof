# CLI

```bash
draftproof [command] [options]
```

Run `draftproof --help` for the full list.

## `draftproof run`

Runs the pipeline once.

```bash
draftproof run --topic "Vector index trade-offs" --words 1400 --sources
draftproof run -t "Observability for LLM apps" --provider groq --model llama-3.3-70b-versatile
draftproof run -t "Zero-downtime migrations" --json
```

| Option | Default | Description |
| --- | --- | --- |
| `--topic`, `-t` | required | Article topic |
| `--audience` | `software engineers` | Target reader |
| `--type` | `explainer` | `explainer`, `tutorial`, `comparison`, `analysis`, `announcement` |
| `--tone` | `practical` | `practical`, `authoritative`, `conversational`, `technical` |
| `--words` | `1400` | Target length (300–6000) |
| `--sources` / `--no-sources` | `--sources` | Require verified citations |
| `--provider` | configured | Override the provider for this run |
| `--model` | configured | Override the model |
| `--data-dir` | `data` | Database and artifact root |
| `--out` | — | Copy artifacts into a directory |
| `--json` | off | Print the run record as JSON |

Exit code is `0` when the run completes (or awaits review) and `1` when it fails or is cancelled.

## `draftproof demo`

A complete offline run with the deterministic mock provider and bundled corpus. No API key, no network, reproducible output.

```bash
draftproof demo --out demo-output
```

Exits `1` if the quality gates fail, which makes it usable as a smoke test.

## `draftproof serve`

```bash
draftproof serve --host 127.0.0.1 --port 8000
```

Starts the API and the studio UI. Use `--provider` to switch providers for the session.

## `draftproof eval`

Scores the golden-case suite and prints a table.

```bash
draftproof eval --cases evals/cases
draftproof eval --cases evals/cases --json
```

Each case asserts a minimum score, gate status, section count, verified claims, cost, duration and required artifacts. Exits `1` if any case fails.

## Inspection commands

```bash
draftproof list --limit 20
draftproof show run_5f0c1d2e3a4b5c6d
draftproof approve run_5f0c1d2e3a4b5c6d --notes "ship it" --reviewer editor
draftproof export run_5f0c1d2e3a4b5c6d --out export/
draftproof doctor
draftproof version
```

`doctor` checks the Python version, data directory writability, database migrations, the configured provider chain, optional provider availability, retriever, verification mode and budget. It exits non-zero when a *required* check fails; optional providers are informational.

## Environment

Every command honours the `DRAFTPROOF_*` variables described in [Configuration](configuration.md). CLI flags take precedence over the environment.
