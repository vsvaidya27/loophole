"""SQLite mirror of the invariant store (invariants.db at the repo root), audit side.

Implements the "Python side" API of docs/INVARIANT_STORE.md for audit workers. Every
write runs the reducer's validation first, so the mirror never holds a row the
SpacetimeDB reducer would reject, and every upsert resets pushed_at to NULL so the
pusher picks it up. Standard library only; one connection per call.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "invariants.db"
EXPLOIT_CLASSES = set(json.loads((Path(__file__).parent / "exploit_classes.json").read_text()))
SOURCES = {"hub", "game", "seed"}
# core.ts ENV_STATUSES, plus the leaderboard's 'unpatched' (see RUN_NOTES.md).
ENV_STATUSES = {
    "queued", "running", "patched", "unpatched", "robust", "failed_to_run",
    "compiling", "pre_hardening", "hardening", "training", "done",
}
MIN_TEXT = 10
MAX_TITLE = 80
MAX_SAMPLE = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_resets (env_id TEXT PRIMARY KEY, requested_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS environments (env_id TEXT PRIMARY KEY, source TEXT, title TEXT, status TEXT,
  updated_at TEXT, pushed_at TEXT, push_error TEXT);
CREATE TABLE IF NOT EXISTS exploits (env_id TEXT, exploit_id TEXT, exploit_class TEXT, iteration INTEGER,
  summary TEXT, sample_completion TEXT, reward_original REAL, reward_patched REAL,
  status TEXT, evidence_path TEXT, confirmed_at TEXT, pushed_at TEXT, push_error TEXT,
  PRIMARY KEY (env_id, exploit_id));
CREATE TABLE IF NOT EXISTS invariants (env_id TEXT NOT NULL, exploit_id TEXT NOT NULL,
  mechanism TEXT, root_cause TEXT, preconditions TEXT, defense_pattern TEXT,
  evidence_path TEXT,
  exploit_class TEXT, title TEXT, embedding_model TEXT, embedding BLOB,
  created_at TEXT, pushed_at TEXT, push_error TEXT,
  PRIMARY KEY (env_id, exploit_id));
CREATE TABLE IF NOT EXISTS rule_applications (run_id TEXT, invariant_id TEXT, target_env_id TEXT,
  outcome TEXT, detail TEXT,
  created_at TEXT, pushed_at TEXT, push_error TEXT,
  PRIMARY KEY (run_id, invariant_id, target_env_id));
"""


class ValidationError(ValueError):
    pass


@dataclass
class Invariant:
    env_id: str
    exploit_id: str
    title: str
    mechanism: str
    root_cause: str
    preconditions: str
    defense_pattern: str
    evidence_path: str
    embedding_model: str = ""
    embedding: bytes | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@contextmanager
def connect(path: Path | None = None):
    con = sqlite3.connect(path or DB_PATH, timeout=10)
    try:
        con.execute("PRAGMA busy_timeout=10000")
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _require_env(con, env_id: str) -> None:
    if con.execute("SELECT 1 FROM environments WHERE env_id = ?", (env_id,)).fetchone() is None:
        raise ValidationError(f"record_environment must be called before writing to {env_id}")


def record_environment(env_id: str, *, source: str, title: str, status: str, db: Path | None = None) -> None:
    if not env_id.strip():
        raise ValidationError("env_id must not be empty")
    if source not in SOURCES:
        raise ValidationError(f"source must be one of {sorted(SOURCES)}; got {source!r}")
    if status not in ENV_STATUSES:
        raise ValidationError(f"status must be one of {sorted(ENV_STATUSES)}; got {status!r}")
    with connect(db) as con:
        con.execute(
            "INSERT INTO environments (env_id, source, title, status, updated_at, pushed_at, push_error) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL) ON CONFLICT(env_id) DO UPDATE SET source = excluded.source, "
            "title = excluded.title, status = excluded.status, updated_at = excluded.updated_at, pushed_at = NULL, push_error = NULL",
            (env_id, source, title, status, _now()),
        )


def record_exploit(env_id: str, exploit_id: str, *, exploit_class: str, iteration: int, summary: str,
                   sample_completion: str, reward_original: float, evidence_path: str, db: Path | None = None) -> None:
    if exploit_class not in EXPLOIT_CLASSES:
        raise ValidationError(f"exploit_class {exploit_class!r} is not in the taxonomy")
    if not isinstance(iteration, int) or not 1 <= iteration <= 5:
        raise ValidationError(f"iteration must be 1..5, got {iteration!r}")
    if not math.isfinite(reward_original):
        raise ValidationError("reward_original must be finite")
    if not exploit_id.strip():
        raise ValidationError("exploit_id must not be empty")
    with connect(db) as con:
        _require_env(con, env_id)
        con.execute(
            "INSERT INTO exploits (env_id, exploit_id, exploit_class, iteration, summary, sample_completion, "
            "reward_original, reward_patched, status, evidence_path, confirmed_at, pushed_at, push_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'confirmed', ?, ?, NULL, NULL) "
            "ON CONFLICT(env_id, exploit_id) DO UPDATE SET exploit_class = excluded.exploit_class, "
            "iteration = excluded.iteration, summary = excluded.summary, sample_completion = excluded.sample_completion, "
            "reward_original = excluded.reward_original, evidence_path = excluded.evidence_path, pushed_at = NULL, push_error = NULL",
            (env_id, exploit_id, exploit_class, iteration, summary, sample_completion[:MAX_SAMPLE], float(reward_original), evidence_path, _now()),
        )


def mark_exploit_patched(env_id: str, exploit_id: str, *, reward_patched: float, db: Path | None = None) -> None:
    if not math.isfinite(reward_patched):
        raise ValidationError("reward_patched must be finite")
    with connect(db) as con:
        cur = con.execute(
            "UPDATE exploits SET reward_patched = ?, status = 'patched', pushed_at = NULL, push_error = NULL "
            "WHERE env_id = ? AND exploit_id = ?",
            (float(reward_patched), env_id, exploit_id),
        )
        if cur.rowcount == 0:
            raise ValidationError(f"no exploit {env_id}#{exploit_id}")


def record_invariant(inv: Invariant, db: Path | None = None) -> None:
    for name in ("mechanism", "root_cause", "preconditions", "defense_pattern"):
        if len(getattr(inv, name).strip()) < MIN_TEXT:
            raise ValidationError(f"{name} must be at least {MIN_TEXT} characters")
    with connect(db) as con:
        row = con.execute(
            "SELECT exploit_class FROM exploits WHERE env_id = ? AND exploit_id = ?", (inv.env_id, inv.exploit_id)
        ).fetchone()
        if row is None:
            raise ValidationError(f"record_exploit must be called before record_invariant ({inv.env_id}#{inv.exploit_id})")
        con.execute(
            "INSERT INTO invariants (env_id, exploit_id, mechanism, root_cause, preconditions, defense_pattern, "
            "evidence_path, exploit_class, title, embedding_model, embedding, created_at, pushed_at, push_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL) "
            "ON CONFLICT(env_id, exploit_id) DO UPDATE SET mechanism = excluded.mechanism, root_cause = excluded.root_cause, "
            "preconditions = excluded.preconditions, defense_pattern = excluded.defense_pattern, "
            "evidence_path = excluded.evidence_path, exploit_class = excluded.exploit_class, title = excluded.title, "
            "embedding_model = excluded.embedding_model, embedding = excluded.embedding, pushed_at = NULL, push_error = NULL",
            (
                inv.env_id, inv.exploit_id, inv.mechanism, inv.root_cause, inv.preconditions, inv.defense_pattern,
                inv.evidence_path, row[0], inv.title[:MAX_TITLE], inv.embedding_model, inv.embedding, _now(),
            ),
        )


def clear_environment(env_id: str, db: Path | None = None) -> None:
    """Mirror half of clear_environment: drop this env's exploit and invariant rows and the
    rule applications that involve it, keeping the environment row. The pusher owns the
    SpacetimeDB half."""
    prefix = f"{env_id}#"
    with connect(db) as con:
        con.execute("INSERT INTO push_resets VALUES (?, ?) ON CONFLICT(env_id) DO UPDATE SET requested_at=excluded.requested_at", (env_id, _now()))
        con.execute("DELETE FROM exploits WHERE env_id = ?", (env_id,))
        con.execute("DELETE FROM invariants WHERE env_id = ?", (env_id,))
        con.execute(
            "DELETE FROM rule_applications WHERE target_env_id = ? OR substr(invariant_id, 1, ?) = ?",
            (env_id, len(prefix), prefix),
        )


def delete_invariant(env_id: str, exploit_id: str, db: Path | None = None) -> None:
    with connect(db) as con:
        con.execute("DELETE FROM invariants WHERE env_id = ? AND exploit_id = ?", (env_id, exploit_id))
        con.execute("DELETE FROM exploits WHERE env_id = ? AND exploit_id = ?", (env_id, exploit_id))


def invariant_rows(env_id: str, db: Path | None = None) -> list[dict]:
    with connect(db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM invariants WHERE env_id = ?", (env_id,))]


def exploit_rows(env_id: str, db: Path | None = None) -> list[dict]:
    with connect(db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM exploits WHERE env_id = ?", (env_id,))]


def record_rule_application(run_id: str, invariant_id: str, target_env_id: str, outcome: str,
                            detail: dict, db: Path | None = None, *,
                            verified_remote_sources: frozenset[str] = frozenset()) -> None:
    if not run_id.strip() or outcome not in {'pre_hardened', 'blocked', 'not_blocked', 'not_applicable'}:
        raise ValidationError('Invalid run ID or application outcome')
    if not isinstance(detail, dict) or type(detail.get('v', 1)) is not int or detail.get('v', 1) != 1:
        raise ValidationError('Application detail must be a version 1 object')
    payload = json.dumps({**detail, 'v': 1}, allow_nan=False)
    with connect(db) as con:
        _require_env(con, target_env_id)
        if invariant_id not in verified_remote_sources and not con.execute("SELECT 1 FROM invariants WHERE env_id || '#' || exploit_id = ?", (invariant_id,)).fetchone():
            raise ValidationError('Source invariant does not exist')
        con.execute("INSERT INTO rule_applications VALUES (?, ?, ?, ?, ?, ?, NULL, NULL) "
                    "ON CONFLICT(run_id,invariant_id,target_env_id) DO UPDATE SET outcome=excluded.outcome, "
                    "detail=excluded.detail,pushed_at=NULL,push_error=NULL",
                    (run_id, invariant_id, target_env_id, outcome, payload, _now()))
