"""SQLite connection management and migration runner.

A single connection guarded by a re-entrant lock is used deliberately: it keeps
``:memory:`` databases usable in tests, makes writes atomic with respect to
readers, and is more than fast enough for the workloads this service sees.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

from draftproof.domain.errors import StorageError

logger = logging.getLogger(__name__)

_MIGRATIONS_PACKAGE = "draftproof.storage"
_MIGRATIONS_DIR = "migrations"


class Database:
    """Owns the SQLite connection, schema migrations and query helpers."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._configure()

    def _configure(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block inside an immediate transaction."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)

    def query_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    def migrate(self) -> list[str]:
        """Apply every pending migration and return their names."""
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row["name"] for row in self._conn.execute("SELECT name FROM schema_migrations")
            }
            newly_applied: list[str] = []
            for name, sql in _migration_files():
                if name in applied:
                    continue
                try:
                    self._conn.executescript(sql)
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) "
                        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                        (name,),
                    )
                except sqlite3.Error as exc:  # pragma: no cover - defensive
                    raise StorageError(f"Migration {name} failed: {exc}") from exc
                newly_applied.append(name)
                logger.info("Applied migration %s", name)
            return newly_applied


def _migration_files() -> list[tuple[str, str]]:
    """Return ``(name, sql)`` pairs ordered by file name."""
    migrations: list[tuple[str, str]] = []
    try:
        base = resources.files(_MIGRATIONS_PACKAGE).joinpath(_MIGRATIONS_DIR)
        entries = sorted(
            (entry for entry in base.iterdir() if entry.name.endswith(".sql")),
            key=lambda entry: entry.name,
        )
        for entry in entries:
            migrations.append((entry.name, entry.read_text(encoding="utf-8")))
    except (OSError, ModuleNotFoundError):  # pragma: no cover - filesystem fallback
        directory = Path(__file__).resolve().parent / _MIGRATIONS_DIR
        for path in sorted(directory.glob("*.sql")):
            migrations.append((path.name, path.read_text(encoding="utf-8")))
    if not migrations:  # pragma: no cover - packaging error
        raise StorageError("No database migrations were found")
    return migrations
