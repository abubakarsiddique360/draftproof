# Deployment

## Docker

```bash
docker build -t draftproof .
docker run --rm -p 8000:8000 -v draftproof-data:/data draftproof
```

The image:

- is multi-stage (build dependencies never ship),
- runs as a non-root `app` user,
- writes the database and artifacts to `/data`,
- defaults to `DRAFTPROOF_PROVIDER=mock`,
- exposes `GET /api/v1/health` as its health check.

### Docker Compose

```bash
DRAFTPROOF_SERVICE_API_KEY=change-me docker compose up --build
```

```yaml
services:
  draftproof:
    build: .
    ports: ["8000:8000"]
    environment:
      DRAFTPROOF_PROVIDER: openai
      DRAFTPROOF_MODEL: gpt-4o-mini
      DRAFTPROOF_API_KEY: ${OPENAI_API_KEY}
      DRAFTPROOF_RETRIEVER: tavily
      DRAFTPROOF_TAVILY_API_KEY: ${TAVILY_API_KEY}
      DRAFTPROOF_SERVICE_API_KEY: ${DRAFTPROOF_SERVICE_API_KEY}
      DRAFTPROOF_DATA_DIR: /data
    volumes: ["draftproof-data:/data"]
```

## Bare metal

```bash
python -m venv /opt/draftproof/.venv
/opt/draftproof/.venv/bin/pip install draftproof
DRAFTPROOF_DATA_DIR=/var/lib/draftproof \
DRAFTPROOF_SERVICE_API_KEY=... \
  /opt/draftproof/.venv/bin/draftproof serve --host 0.0.0.0 --port 8000
```

Put it behind a reverse proxy that terminates TLS:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;          # required for SSE
    proxy_read_timeout 3600s;
}
```

`proxy_buffering off` matters: buffering delays the live event stream.

## Platform notes

| Concern | Guidance |
| --- | --- |
| Persistence | Back up `DRAFTPROOF_DATA_DIR` (SQLite database + artifacts). |
| Replicas | Each replica needs its own data volume; the run manager and rate limiter are process-local. |
| Scaling out | Swap the repository for Postgres and move rate limiting to the edge (see the roadmap). |
| Secrets | Inject keys with your platform's secret store, never in the image. |
| Cost | Set `DRAFTPROOF_MAX_COST_USD` per environment; the router enforces it before every call. |
| Egress | Restrict outbound traffic to the provider endpoints plus the domains you allow for verification. |

## Health checks

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health
```

Returns `200` when the database answers. Use `/api/v1/meta` to confirm which provider chain and verification mode a deployment is actually running.

## Observability

- `/api/v1/metrics` for Prometheus scrape (runs created/finished, tokens, HTTP requests, active runs).
- The `events` table and SSE stream for per-run timelines.
- Structured logs on stderr via `DRAFTPROOF_LOG_LEVEL`.
- `manifest.json` per run for a post-hoc audit of models, costs, evidence and hashes.
