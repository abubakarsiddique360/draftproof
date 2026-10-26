"""Artifact store safety and atomic writes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from draftproof.domain.errors import StorageError
from draftproof.storage.files import ARTIFACT_FILENAMES, ArtifactStore, new_run_id, slugify


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


def test_write_and_read(store: ArtifactStore) -> None:
    run_id = new_run_id()
    artifact = store.write(run_id, "markdown", "# Title\n")
    assert artifact.bytes == len("# Title\n")
    assert artifact.sha256 == hashlib.sha256(b"# Title\n").hexdigest()
    assert artifact.relative_path == f"{run_id}/article.md"
    assert store.read_text(run_id, "markdown") == "# Title\n"
    leftovers = [path for path in store.run_dir(run_id).iterdir() if path.name.startswith(".")]
    assert leftovers == []


def test_unknown_kind_rejected(store: ArtifactStore) -> None:
    run_id = new_run_id()
    with pytest.raises(StorageError):
        store.write(run_id, "secrets", "nope")
    assert set(ARTIFACT_FILENAMES) >= {"markdown", "html", "manifest"}


def test_invalid_run_id_rejected(store: ArtifactStore) -> None:
    with pytest.raises(StorageError):
        store.write("../escape", "markdown", "bad")
    with pytest.raises(StorageError):
        store.write("short", "markdown", "bad")


def test_resolve_blocks_traversal(store: ArtifactStore) -> None:
    run_id = new_run_id()
    store.write(run_id, "markdown", "ok")
    assert store.resolve(f"{run_id}/article.md").exists()
    with pytest.raises(StorageError):
        store.resolve("../../etc/passwd")


def test_missing_artifact_raises(store: ArtifactStore) -> None:
    with pytest.raises(StorageError):
        store.read_text(new_run_id(), "html")


def test_slugify() -> None:
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("   ") == "untitled"
    assert len(slugify("a" * 200)) <= 60


def test_overwrite_updates_hash(store: ArtifactStore) -> None:
    run_id = new_run_id()
    first = store.write(run_id, "html", "one")
    second = store.write(run_id, "html", "two")
    assert first.sha256 != second.sha256
    assert store.read_text(run_id, "html") == "two"
