"""Database schema definitions for EntireContext."""

SCHEMA_VERSION = 5

# Minimum SQLite version required (for JSON functions)
MIN_SQLITE_VERSION = "3.38.0"

TABLES = {
    "schema_version": """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now')),
    description TEXT
);
""",
    "projects": """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repo_path TEXT NOT NULL UNIQUE,
    remote_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    config TEXT
);
""",
    "agents": """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    parent_agent_id TEXT,
    agent_type TEXT NOT NULL,
    role TEXT,
    name TEXT,
    spawn_context TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (parent_agent_id) REFERENCES agents(id)
);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id);
CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type);
""",
    "sessions": """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    agent_id TEXT,
    session_type TEXT NOT NULL,
    workspace_path TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_activity_at TEXT NOT NULL,
    session_title TEXT,
    session_summary TEXT,
    summary_updated_at TEXT,
    total_turns INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_activity ON sessions(last_activity_at DESC);
""",
    "turns": """
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    user_message TEXT,
    assistant_summary TEXT,
    turn_status TEXT,
    model_name TEXT,
    git_commit_hash TEXT,
    files_touched TEXT,
    tools_used TEXT,
    content_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    consolidated_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, turn_number),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turns_commit ON turns(git_commit_hash);
CREATE INDEX IF NOT EXISTS idx_turns_consolidated ON turns(consolidated_at);
""",
    "turn_content": """
CREATE TABLE IF NOT EXISTS turn_content (
    turn_id TEXT PRIMARY KEY,
    content_path TEXT NOT NULL,
    content_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE CASCADE
);
""",
    "checkpoints": """
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    git_commit_hash TEXT NOT NULL,
    git_branch TEXT,
    parent_checkpoint_id TEXT,
    files_snapshot TEXT,
    diff_summary TEXT,
    agent_state TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_checkpoint_id) REFERENCES checkpoints(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_commit ON checkpoints(git_commit_hash);
CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at DESC);
""",
    "events": """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    start_timestamp TEXT,
    end_timestamp TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT
);
""",
    "event_sessions": """
CREATE TABLE IF NOT EXISTS event_sessions (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, session_id),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
""",
    "event_checkpoints": """
CREATE TABLE IF NOT EXISTS event_checkpoints (
    event_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, checkpoint_id),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE CASCADE
);
""",
    "attributions": """
CREATE TABLE IF NOT EXISTS attributions (
    id TEXT PRIMARY KEY,
    checkpoint_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    attribution_type TEXT NOT NULL,
    agent_id TEXT,
    session_id TEXT,
    turn_id TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_attributions_checkpoint ON attributions(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_attributions_file ON attributions(file_path);
CREATE INDEX IF NOT EXISTS idx_attributions_agent ON attributions(agent_id);
""",
    "embeddings": """
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    vector BLOB NOT NULL,
    dimensions INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model_name);
""",
    "assessments": """
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    checkpoint_id TEXT,
    verdict TEXT NOT NULL,
    impact_summary TEXT,
    roadmap_alignment TEXT,
    tidy_suggestion TEXT,
    diff_summary TEXT,
    feedback TEXT,
    feedback_reason TEXT,
    model_name TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_assessments_verdict ON assessments(verdict);
CREATE INDEX IF NOT EXISTS idx_assessments_created ON assessments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assessments_checkpoint ON assessments(checkpoint_id);
""",
    "assessment_relationships": """
CREATE TABLE IF NOT EXISTS assessment_relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    CHECK (source_id != target_id),
    UNIQUE(source_id, target_id, relationship_type),
    FOREIGN KEY (source_id) REFERENCES assessments(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES assessments(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_assessment_rel_source ON assessment_relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_assessment_rel_target ON assessment_relationships(target_id);
""",
    "sync_metadata": """
CREATE TABLE IF NOT EXISTS sync_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_export_at TEXT,
    last_import_at TEXT,
    sync_status TEXT DEFAULT 'idle',
    last_sync_error TEXT,
    last_sync_duration_ms INTEGER,
    sync_pid INTEGER
);
""",
}

# FTS5 virtual tables
FTS_TABLES = {
    "fts_turns": """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_turns USING fts5(
    user_message,
    assistant_summary,
    content='turns',
    content_rowid='rowid'
);
""",
    "fts_events": """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_events USING fts5(
    title,
    description,
    content='events',
    content_rowid='rowid'
);
""",
    "fts_sessions": """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_sessions USING fts5(
    session_title,
    session_summary,
    content='sessions',
    content_rowid='rowid'
);
""",
}

# FTS5 sync triggers (9 total: 3 per FTS table)
FTS_TRIGGERS = {
    "fts_turns_ai": """
CREATE TRIGGER IF NOT EXISTS fts_turns_ai AFTER INSERT ON turns BEGIN
  INSERT INTO fts_turns(rowid, user_message, assistant_summary)
  VALUES (new.rowid, new.user_message, new.assistant_summary);
END;
""",
    "fts_turns_ad": """
CREATE TRIGGER IF NOT EXISTS fts_turns_ad AFTER DELETE ON turns BEGIN
  INSERT INTO fts_turns(fts_turns, rowid, user_message, assistant_summary)
  VALUES ('delete', old.rowid, old.user_message, old.assistant_summary);
END;
""",
    "fts_turns_au": """
CREATE TRIGGER IF NOT EXISTS fts_turns_au AFTER UPDATE ON turns BEGIN
  INSERT INTO fts_turns(fts_turns, rowid, user_message, assistant_summary)
  VALUES ('delete', old.rowid, old.user_message, old.assistant_summary);
  INSERT INTO fts_turns(rowid, user_message, assistant_summary)
  VALUES (new.rowid, new.user_message, new.assistant_summary);
END;
""",
    "fts_events_ai": """
CREATE TRIGGER IF NOT EXISTS fts_events_ai AFTER INSERT ON events BEGIN
  INSERT INTO fts_events(rowid, title, description)
  VALUES (new.rowid, new.title, new.description);
END;
""",
    "fts_events_ad": """
CREATE TRIGGER IF NOT EXISTS fts_events_ad AFTER DELETE ON events BEGIN
  INSERT INTO fts_events(fts_events, rowid, title, description)
  VALUES ('delete', old.rowid, old.title, old.description);
END;
""",
    "fts_events_au": """
CREATE TRIGGER IF NOT EXISTS fts_events_au AFTER UPDATE ON events BEGIN
  INSERT INTO fts_events(fts_events, rowid, title, description)
  VALUES ('delete', old.rowid, old.title, old.description);
  INSERT INTO fts_events(rowid, title, description)
  VALUES (new.rowid, new.title, new.description);
END;
""",
    "fts_sessions_ai": """
CREATE TRIGGER IF NOT EXISTS fts_sessions_ai AFTER INSERT ON sessions BEGIN
  INSERT INTO fts_sessions(rowid, session_title, session_summary)
  VALUES (new.rowid, new.session_title, new.session_summary);
END;
""",
    "fts_sessions_ad": """
CREATE TRIGGER IF NOT EXISTS fts_sessions_ad AFTER DELETE ON sessions BEGIN
  INSERT INTO fts_sessions(fts_sessions, rowid, session_title, session_summary)
  VALUES ('delete', old.rowid, old.session_title, old.session_summary);
END;
""",
    "fts_sessions_au": """
CREATE TRIGGER IF NOT EXISTS fts_sessions_au AFTER UPDATE ON sessions BEGIN
  INSERT INTO fts_sessions(fts_sessions, rowid, session_title, session_summary)
  VALUES ('delete', old.rowid, old.session_title, old.session_summary);
  INSERT INTO fts_sessions(rowid, session_title, session_summary)
  VALUES (new.rowid, new.session_title, new.session_summary);
END;
""",
}


def get_all_schema_sql() -> list[str]:
    """Return all SQL statements needed to create the full schema."""
    statements = []
    for sql in TABLES.values():
        statements.extend(s.strip() for s in sql.strip().split(";") if s.strip())
    for sql in FTS_TABLES.values():
        statements.append(sql.strip().rstrip(";"))
    for sql in FTS_TRIGGERS.values():
        # Triggers contain semicolons inside, handle carefully
        statements.append(sql.strip())
    return statements
