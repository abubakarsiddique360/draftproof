PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    topic TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    parent_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    outline_json TEXT,
    quality_json TEXT,
    error TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    llm_calls INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS sections (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    section_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    markdown TEXT NOT NULL DEFAULT '',
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'drafted',
    grounding REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, section_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    snippet TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    overlap REAL NOT NULL DEFAULT 0,
    content_hash TEXT,
    source TEXT,
    injection_suspected INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS claims (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    note TEXT,
    PRIMARY KEY (run_id, claim_id)
);

CREATE INDEX IF NOT EXISTS idx_claims_section ON claims(run_id, section_id);

CREATE TABLE IF NOT EXISTS stages (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    detail TEXT,
    PRIMARY KEY (run_id, stage, attempt)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    type TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, kind)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT 'editor',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews(run_id, id);
