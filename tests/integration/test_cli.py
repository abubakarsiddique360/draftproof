"""CLI smoke tests through the Typer runner."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from draftproof.cli import app

runner = CliRunner()
CASES = Path(__file__).resolve().parents[2] / "evals" / "cases"


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "DraftProof" in result.stdout


def test_doctor(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path / "data")])
    assert result.exit_code == 0, result.stdout
    assert "provider:mock" in result.stdout


def test_demo_writes_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "demo",
            "--data-dir",
            str(tmp_path / "data"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "article.md").exists()
    assert (out / "manifest.json").exists()


def test_run_json_and_list(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    result = runner.invoke(
        app,
        [
            "run",
            "--topic",
            "Zero-downtime database migrations",
            "--words",
            "600",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "completed" in result.stdout

    listing = runner.invoke(app, ["list", "--data-dir", str(data_dir)])
    assert listing.exit_code == 0
    assert "Zero-downtime" in listing.stdout


def test_show_returns_json(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    created = runner.invoke(
        app,
        [
            "run",
            "--topic",
            "Observability for LLM applications",
            "--words",
            "600",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert created.exit_code == 0, created.stdout
    listing = runner.invoke(app, ["list", "--data-dir", str(data_dir)])
    connection = sqlite3.connect(data_dir / "draftproof.db")
    try:
        run_id = connection.execute("SELECT id FROM runs LIMIT 1").fetchone()[0]
    finally:
        connection.close()
    assert run_id[:12] in listing.stdout
    assert "Observability" in listing.stdout
    shown = runner.invoke(app, ["show", run_id, "--data-dir", str(data_dir)])
    assert shown.exit_code == 0
    assert run_id in shown.stdout


def test_run_rejects_invalid_type(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "--topic", "A valid topic", "--type", "nonsense", "--data-dir", str(tmp_path)],
    )
    assert result.exit_code == 2


@pytest.mark.slow
def test_eval_suite_passes(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["eval", "--cases", str(CASES), "--data-dir", str(tmp_path / "eval")],
    )
    assert result.exit_code == 0, result.stdout
    assert "4/4 passed" in result.stdout


def test_eval_json_output(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["eval", "--cases", str(CASES), "--data-dir", str(tmp_path / "eval"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    start = result.stdout.index("{")
    payload = json.loads(result.stdout[start:])
    assert payload["total"] == 4
    assert payload["failed"] == 0
