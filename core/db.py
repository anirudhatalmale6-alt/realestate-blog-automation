"""SQLite storage for the blog automation pipeline."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get(
    "BLOGBOT_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "blogbot.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS keywords (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase        TEXT NOT NULL UNIQUE,
    intent        TEXT NOT NULL DEFAULT 'informational',
    locality      TEXT,
    priority      INTEGER NOT NULL DEFAULT 5,
    times_used    INTEGER NOT NULL DEFAULT 0,
    last_used_at  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id     INTEGER REFERENCES keywords(id),
    title          TEXT NOT NULL,
    slug           TEXT NOT NULL,
    excerpt        TEXT,
    body_html      TEXT NOT NULL,
    meta_title     TEXT,
    meta_desc      TEXT,
    word_count     INTEGER NOT NULL DEFAULT 0,
    provider       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending_review',
    scheduled_for  TEXT,
    published_at   TEXT,
    remote_id      TEXT,
    remote_url     TEXT,
    review_note    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER,
    kind       TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);

-- Future social distribution. Nothing writes to this yet; the hook in
-- publisher.py fans out to whatever rows live here once channels are added.
CREATE TABLE IF NOT EXISTS distribution_channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,          -- facebook_page | linkedin | x | instagram
    label      TEXT NOT NULL,
    config     TEXT,                   -- JSON blob: tokens, page ids, etc.
    enabled    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS distribution_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER NOT NULL REFERENCES posts(id),
    channel_id  INTEGER NOT NULL REFERENCES distribution_channels(id),
    status      TEXT NOT NULL DEFAULT 'queued',
    run_at      TEXT,
    payload     TEXT,
    result      TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_sched  ON posts(scheduled_for);
"""

# status values a post moves through
PENDING = "pending_review"
APPROVED = "approved"      # approved but not yet given a slot
SCHEDULED = "scheduled"
PUBLISHED = "published"
REJECTED = "rejected"
PAUSED = "paused"


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def log_event(conn, post_id, kind, detail=""):
    conn.execute(
        "INSERT INTO events (post_id, kind, detail, created_at) VALUES (?,?,?,?)",
        (post_id, kind, detail, now()),
    )


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
