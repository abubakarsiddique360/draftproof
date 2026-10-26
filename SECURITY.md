# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.x` | ✅ |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting on this repository (Security → Report a vulnerability) with:

- a description of the issue and its impact,
- the affected version and configuration,
- reproduction steps or a proof of concept,
- any suggested remediation.

You can expect an acknowledgement within 72 hours and a status update within 7 days.

## Threat model

DraftProof runs model output and web content through a publishing pipeline, so the boundaries that matter are:

| Surface | Mitigation |
| --- | --- |
| Prompt injection from retrieved text | Markup stripped, length capped, instruction-like phrases removed and flagged, evidence fenced and labelled untrusted |
| SSRF through citation URLs | Only `http`/`https`, no embedded credentials, DNS resolution checked against private/loopback/link-local/reserved ranges, every redirect hop revalidated, byte caps and timeouts |
| Stored XSS in exported HTML | Markdown rendered with raw HTML disabled, then passed through a tag/attribute allow-list sanitiser; JSON-LD is escaped so it cannot close its script element |
| Filesystem traversal | Run ids validated against a strict pattern, artifact names come from a fixed allow-list, resolved paths must stay under the artifact root |
| Credential leakage | Secrets are `SecretStr`, never serialised into the manifest, snapshots or API responses |
| Unauthenticated access | Optional `X-API-Key` on every `/api/v1` route except `/health` and `/meta`, compared in constant time |
| Request floods | Per-client token bucket, request body size cap, bounded thread pool |
| Cost blow-ups | Hard per-run USD budget enforced by the router before every call |

## Operational hardening

- Always set `DRAFTPROOF_SERVICE_API_KEY` when exposing the service beyond localhost.
- Put the service behind TLS; it does not terminate TLS itself.
- Restrict `DRAFTPROOF_ALLOWED_DOMAINS` when fetching from the public web.
- Keep `DRAFTPROOF_MAX_COST_USD`, `DRAFTPROOF_CONCURRENCY` and `DRAFTPROOF_FETCH_MAX_BYTES` at values you can afford.
- Run the container as the provided non-root user and mount `/data` on a dedicated volume.

## Out of scope

- Content accuracy of third-party sources (DraftProof reports support, not truth).
- Denial of service through a hostile model provider you configured yourself.
