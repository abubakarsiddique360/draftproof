"""HTTP API: runs, streaming, artifacts, review flow and security."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from draftproof.api.app import create_app
from draftproof.config import Settings
from draftproof.pipeline.service import RunService

TERMINAL = {"completed", "failed", "cancelled", "awaiting_review"}


@pytest.fixture()
def client(settings: Settings, service: RunService) -> Iterator[TestClient]:
    app = create_app(settings, service=service)
    with TestClient(app) as test_client:
        yield test_client


def _wait(client: TestClient, run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.1)
    raise AssertionError(f"run did not finish in time: {last}")


def _create(client: TestClient, topic: str = "Retrieval-augmented generation in production") -> str:
    response = client.post(
        "/api/v1/runs",
        json={"topic": topic, "target_words": 700, "sources_required": True},
    )
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_health_and_meta(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"

    meta = client.get("/api/v1/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["provider_chain"] == ["mock"]
    assert body["api_key_required"] is False
    assert any(
        provider["name"] == "mock" and provider["available"] for provider in body["providers"]
    )


def test_full_run_lifecycle(client: TestClient) -> None:
    run_id = _create(client)
    finished = _wait(client, run_id)

    assert finished["status"] == "completed"
    assert finished["quality"]["passed"] is True
    assert finished["sections"]
    assert {artifact["kind"] for artifact in finished["artifacts"]} >= {"markdown", "manifest"}

    page = client.get("/api/v1/runs?limit=5")
    assert page.status_code == 200
    assert page.json()["total"] >= 1

    markdown = client.get(f"/api/v1/runs/{run_id}/artifacts/markdown")
    assert markdown.status_code == 200
    assert "text/markdown" in markdown.headers["content-type"]
    assert markdown.text.startswith("---")

    manifest = client.get(f"/api/v1/runs/{run_id}/artifacts/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["run"]["id"] == run_id


def test_sse_replays_history(client: TestClient) -> None:
    run_id = _create(client)
    _wait(client, run_id)

    with client.stream("GET", f"/api/v1/runs/{run_id}/events?after=0") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = "".join(response.iter_text())

    assert "event: run_started" in payload
    assert "event: run_finished" in payload
    assert "event: stream_end" in payload


def test_unknown_run_and_artifact(client: TestClient) -> None:
    missing = client.get("/api/v1/runs/run_missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "run_not_found"

    run_id = _create(client)
    _wait(client, run_id)
    unknown = client.get(f"/api/v1/runs/{run_id}/artifacts/secrets")
    assert unknown.status_code == 404


def test_validation_errors_are_structured(client: TestClient) -> None:
    response = client.post("/api/v1/runs", json={"topic": "ai"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]

    extra = client.post("/api/v1/runs", json={"topic": "valid topic", "nope": 1})
    assert extra.status_code == 422


def test_cancel_and_resume_conflicts(client: TestClient) -> None:
    run_id = _create(client)
    _wait(client, run_id)
    cancel = client.delete(f"/api/v1/runs/{run_id}")
    assert cancel.status_code == 200
    assert cancel.json()["cancelled"] is False

    resume = client.post(f"/api/v1/runs/{run_id}/resume")
    assert resume.status_code == 409


def test_review_flow(client: TestClient) -> None:
    run_id = _create(client)
    _wait(client, run_id)

    conflict = client.post(
        f"/api/v1/runs/{run_id}/review", json={"decision": "approve", "notes": ""}
    )
    assert conflict.status_code == 409

    changes = client.post(
        f"/api/v1/runs/{run_id}/review",
        json={"decision": "request_changes", "notes": "Sharpen it."},
    )
    assert changes.status_code == 202
    finished = _wait(client, run_id)
    assert finished["status"] == "completed"
    assert finished["reviews"][-1]["decision"] == "request_changes"


def test_regenerate_unknown_section(client: TestClient) -> None:
    run_id = _create(client)
    _wait(client, run_id)
    response = client.post(f"/api/v1/runs/{run_id}/sections/s99/regenerate", json={"notes": "x"})
    assert response.status_code == 404


def test_metrics_and_rubric(client: TestClient) -> None:
    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    assert "draftproof_active_runs" in metrics.text

    _create(client)
    after = client.get("/api/v1/metrics")
    assert "draftproof_runs_created_total" in after.text

    rubric = client.get("/api/v1/rubric")
    assert rubric.status_code == 200
    assert set(rubric.json()["weights"]) >= {"structure", "citation_coverage"}


def test_api_key_is_enforced(settings: Settings, service: RunService) -> None:
    secured = settings.model_copy(update={"service_api_key": SecretStr("topsecret")})
    app = create_app(secured, service=service)
    with TestClient(app) as secured_client:
        assert secured_client.get("/api/v1/health").status_code == 200
        unauthorized = secured_client.get("/api/v1/runs")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "unauthorized"
        authorized = secured_client.get("/api/v1/runs", headers={"X-API-Key": "topsecret"})
        assert authorized.status_code == 200


def test_rate_limit_blocks_burst(settings: Settings, service: RunService) -> None:
    limited = settings.model_copy(update={"rate_limit_per_minute": 1})
    app = create_app(limited, service=service)
    with TestClient(app) as limited_client:
        assert limited_client.get("/api/v1/runs").status_code == 200
        blocked = limited_client.get("/api/v1/runs")
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "rate_limited"


def test_studio_shell_is_served(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "DraftProof Studio" in index.text
    assert index.headers["content-security-policy"]
    assert client.get("/js/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
