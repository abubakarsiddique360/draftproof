"""Safe artifact persistence.

Artifact names are drawn from a fixed allow-list and run identifiers are
validated, so neither a model nor an API caller can escape the artifact root.
Writes are atomic (temporary file plus ``os.replace``).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from draftproof.domain.errors import StorageError
from draftproof.domain.models import Artifact, utc_now

_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{5,63}$")
_SLUG = re.compile(r"[^a-z0-9]+")

ARTIFACT_FILENAMES: dict[str, str] = {
    "markdown": "article.md",
    "html": "article.html",
    "jsonld": "article.jsonld.json",
    "social": "social.json",
    "manifest": "manifest.json",
    "quality": "quality.json",
    "outline": "outline.json",
}


def new_run_id() -> str:
    """Return a fresh, filesystem-safe run identifier."""
    return f"run_{uuid.uuid4().hex[:16]}"


def slugify(value: str, *, max_length: int = 60) -> str:
    """Convert arbitrary text into a lowercase hyphenated slug."""
    slug = _SLUG.sub("-", value.strip().lower()).strip("-")
    if not slug:
        return "untitled"
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0].strip("-") or slug[:max_length]
    return slug


def validate_run_id(run_id: str) -> str:
    """Validate a run identifier or raise ``StorageError``."""
    if not _RUN_ID.match(run_id):
        raise StorageError(f"Invalid run id: {run_id!r}")
    return run_id


class ArtifactStore:
    """Writes run artifacts beneath a single root directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        validate_run_id(run_id)
        directory = self.root / run_id
        resolved = directory.resolve()
        if self.root not in resolved.parents and resolved != self.root:
            raise StorageError("Resolved artifact path escaped the artifact root")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def filename_for(self, kind: str) -> str:
        try:
            return ARTIFACT_FILENAMES[kind]
        except KeyError as exc:
            raise StorageError(f"Unknown artifact kind: {kind!r}") from exc

    def path_for(self, run_id: str, kind: str) -> Path:
        return self.run_dir(run_id) / self.filename_for(kind)

    def write(self, run_id: str, kind: str, data: str | bytes) -> Artifact:
        """Atomically write ``data`` and return its manifest entry."""
        path = self.path_for(run_id, kind)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        return Artifact(
            kind=kind,
            relative_path=f"{run_id}/{path.name}",
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
            created_at=utc_now(),
        )

    def read_text(self, run_id: str, kind: str) -> str:
        path = self.path_for(run_id, kind)
        if not path.exists():
            raise StorageError(f"Artifact {kind} does not exist for run {run_id}")
        return path.read_text(encoding="utf-8")

    def resolve(self, relative_path: str) -> Path:
        """Resolve a stored relative path, rejecting traversal escapes."""
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError("Artifact path escaped the artifact root")
        return candidate
