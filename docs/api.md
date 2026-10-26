# HTTP API

Base path: `/api/v1`. Interactive documentation: `/api/docs`. OpenAPI document: `/api/openapi.json`.

All errors share one envelope:

```json
{
  "error": {
    "code": "run_not_found",
    "message": "Run 'run_abc' was not found",
    "hint": "Check the id from GET /api/v1/runs."
  }
}
```

| Status | When |
| --- | --- |
| `401` | API key missing or wrong (`DRAFTPROOF_SERVICE_API_KEY` set) |
| `402` | Run budget exhausted |
| `404` | Unknown run, section or artifact |
| `409` | Invalid state transition (approve twice, resume a completed run) |
| `413` | Request body above `DRAFTPROOF_MAX_BODY_BYTES` |
| `422` | Validation failure (includes per-field details) |
| `429` | Rate limit exceeded |
| `502` | Provider failure |

## Authentication

When `DRAFTPROOF_SERVICE_API_KEY` is set, every route except `/health` and `/meta` requires:

```http
X-API-Key: <key>
```

Keys are compared in constant time. The studio UI stores the key in `localStorage` and sends it with every request, including streamed downloads.

## Endpoints

### `GET /health`

```json
{ "status": "ok", "version": "0.1.0", "database": "ok", "uptime_seconds": 42.1 }
```

### `GET /meta`

```json
{
  "name": "DraftProof",
  "version": "0.1.0",
  "provider_chain": ["mock"],
  "retriever": "local_corpus",
  "verification": "corpus",
  "review_required": false,
  "api_key_required": false,
  "limits": { "max_cost_usd": 1.0, "concurrency": 4 },
  "providers": [{ "name": "mock", "kind": "mock", "model": "mock-writer-1", "available": true }]
}
```

### `POST /runs`

```json
{
  "topic": "Retrieval-augmented generation in production",
  "audience": "software engineers",
  "content_type": "explainer",
  "tone": "practical",
  "target_words": 1400,
  "key_points": ["Chunking and freshness"],
  "must_include": [],
  "must_avoid": [],
  "sources_required": true,
  "language": "en",
  "seed": 7
}
```

`202 Accepted`:

```json
{
  "run_id": "run_5f0c...",
  "status": "queued",
  "topic": "...",
  "stream_url": "/api/v1/runs/run_5f0c.../events"
}
```

### `GET /runs`

Query: `limit` (1–100, default 20), `offset`, `status`.

```json
{
  "items": [
    {
      "id": "run_5f0c...",
      "topic": "...",
      "status": "completed",
      "provider": "mock",
      "model": "mock-writer-1",
      "score": 93.96,
      "passed": true,
      "created_at": "2026-10-26T09:00:00Z",
      "cost_usd": 0.0
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### `GET /runs/{id}`

Returns the full `RunRecord`: brief, outline, sections (with markdown and claims), evidence, quality report, usage, artifacts, reviews and error (if any).

### `GET /runs/{id}/events`

Server-Sent Events. `?after=<seq>` replays from a sequence number.

```text
id: 12
event: quality_scored
data: {"score":93.96,"grade":"A","passed":true,...}
```

The stream ends with `event: stream_end` when the run is terminal or awaiting review. Heartbeats are sent as `: keep-alive` comments.

### `GET /runs/{id}/artifacts/{kind}`

`kind` ∈ `markdown`, `html`, `jsonld`, `social`, `manifest`, `quality`, `outline`. Markdown and HTML are served inline; the rest are attachments.

### `POST /runs/{id}/review`

```json
{ "decision": "approve", "notes": "ship it", "reviewer": "editor" }
```

- `approve` → `200`, run becomes `completed`. Requires status `awaiting_review`.
- `request_changes` → `202`, a background revision re-drafts, re-verifies, re-scores and re-publishes. Optional `section_ids` limits the rewrite.

### `POST /runs/{id}/sections/{sid}/regenerate`

```json
{ "notes": "Add a comparison table", "reviewer": "editor" }
```

`202`. Only the named section is re-drafted; the rest of the document is untouched unless the rubric then demands a revision.

### `DELETE /runs/{id}`

Requests cancellation and returns `{ "run_id": "...", "cancelled": true, "status": "cancelling" }`. Cancellation is cooperative and process-local.

### `POST /runs/{id}/resume`

Resumes a `failed` or `cancelled` run from its last checkpoint. `409` for any other state.

### `GET /rubric`

```json
{
  "weights": { "structure": 0.18, "citation_coverage": 0.18, "...": 0.0 },
  "gates": [{ "key": "score", "minimum": 75.0, "condition": "always" }],
  "flesch_target": [40.0, 65.0]
}
```

### `GET /metrics`

Prometheus text format:

```text
# TYPE draftproof_runs_created_total counter
draftproof_runs_created_total 3
# TYPE draftproof_runs_finished_total counter
draftproof_runs_finished_total{status="completed"} 3
# TYPE draftproof_http_requests_total counter
draftproof_http_requests_total{route="create_run"} 3
# TYPE draftproof_active_runs gauge
draftproof_active_runs 0
```

## Client example

```python
import httpx, time

base = "http://127.0.0.1:8000/api/v1"
created = httpx.post(f"{base}/runs", json={"topic": "Vector search trade-offs"}).json()
run_id = created["run_id"]

for _ in range(300):
    run = httpx.get(f"{base}/runs/{run_id}").json()
    if run["status"] in {"completed", "failed", "cancelled", "awaiting_review"}:
        break
    time.sleep(0.2)

print(run["status"], run["quality"]["score"], run["quality"]["passed"])
```
