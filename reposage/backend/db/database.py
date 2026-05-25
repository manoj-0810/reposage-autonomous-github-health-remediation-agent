"""
RepoSage — PostgreSQL persistence layer.
Uses ``asyncpg`` for async connections.  Tables:
  * scans        — one row per scan
  * findings     — individual audit findings
  * scan_history — time-series health scores per repo (for sparkline)
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg

DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://reposage:reposage@localhost:5432/reposage",
)

# SQL to bootstrap the schema on first connection.
_INIT_SQL = """
CREATE TABLE IF NOT EXISTS scans (
    scan_id         TEXT PRIMARY KEY,
    repo_url        TEXT NOT NULL,
    owner           TEXT NOT NULL,
    repo            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    health_overall  REAL,
    health_security REAL,
    health_deps     REAL,
    health_quality  REAL,
    health_coverage REAL,
    findings_json   JSONB,
    patches_json    JSONB,
    actions_json    JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS findings (
    id              SERIAL PRIMARY KEY,
    scan_id         TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    severity        TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    line_start      INT,
    line_end        INT,
    description     TEXT NOT NULL,
    suggested_fix   TEXT,
    fix_complexity  INT DEFAULT 3,
    auto_fixable    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scan_history (
    id          SERIAL PRIMARY KEY,
    owner       TEXT NOT NULL,
    repo        TEXT NOT NULL,
    scan_id     TEXT NOT NULL,
    scanned_at  TIMESTAMPTZ DEFAULT NOW(),
    overall     REAL NOT NULL,
    security    REAL NOT NULL,
    deps        REAL NOT NULL,
    quality     REAL NOT NULL,
    coverage    REAL NOT NULL,
    UNIQUE(owner, repo, scan_id)
);

CREATE INDEX IF NOT EXISTS idx_scans_owner_repo ON scans(owner, repo);
CREATE INDEX IF NOT EXISTS idx_history_owner_repo ON scan_history(owner, repo, scanned_at DESC);
"""

_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn):
    await conn.set_type_codec(
        'jsonb',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )
    await conn.set_type_codec(
        'json',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )

async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(
            DSN,
            min_size=2,
            max_size=10,
            init=_init_connection,
        )
        async with _pool.acquire() as conn:
            await conn.execute(_INIT_SQL)
    return _pool


@asynccontextmanager
async def get_conn():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        yield conn


# ── public CRUD ──────────────────────────────────────────────────────────

async def create_scan(
    scan_id: str,
    repo_url: str,
    owner: str,
    repo: str,
) -> None:
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO scans (scan_id, repo_url, owner, repo, status)
            VALUES ($1, $2, $3, $4, 'running')
            ON CONFLICT (scan_id) DO NOTHING
            """,
            scan_id, repo_url, owner, repo,
        )


async def update_scan_status(
    scan_id: str,
    status: str,
    health: Optional[Any] = None,
    findings: Optional[List[Any]] = None,
    patches: Optional[List[Any]] = None,
    actions: Optional[Any] = None,
) -> None:
    async with get_conn() as conn:
        updates = ["status = $2"]
        params: List[Any] = [scan_id, status]
        idx = 3
        if health is not None:
            updates.append(f"health_overall = ${idx}")
            params.append(health.overall)
            idx += 1
            updates.append(f"health_security = ${idx}")
            params.append(health.security)
            idx += 1
            updates.append(f"health_deps = ${idx}")
            params.append(health.dependencies)
            idx += 1
            updates.append(f"health_quality = ${idx}")
            params.append(health.code_quality)
            idx += 1
            updates.append(f"health_coverage = ${idx}")
            params.append(health.test_coverage)
            idx += 1
        if findings is not None:
            updates.append(f"findings_json = ${idx}::jsonb")
            params.append(json.dumps([f.model_dump() for f in findings]))
            idx += 1
        if patches is not None:
            updates.append(f"patches_json = ${idx}::jsonb")
            params.append(json.dumps([p.model_dump() for p in patches]))
            idx += 1
        if actions is not None:
            updates.append(f"actions_json = ${idx}::jsonb")
            params.append(json.dumps(actions))
            idx += 1
        if status in ("completed", "error"):
            updates.append("completed_at = NOW()")

        sql = f"UPDATE scans SET {', '.join(updates)} WHERE scan_id = $1"
        await conn.execute(sql, *params)

        # insert findings rows for easy querying
        if findings is not None:
            for f in findings:
                line_range = f.line_range
                await conn.execute(
                    """
                    INSERT INTO findings
                    (scan_id, category, severity, file_path, line_start, line_end,
                     description, suggested_fix, fix_complexity, auto_fixable)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT DO NOTHING
                    """,
                    scan_id,
                    f.category.value,
                    f.severity.value,
                    f.file_path,
                    line_range[0] if line_range else None,
                    line_range[1] if line_range else None,
                    f.description,
                    f.suggested_fix,
                    f.fix_complexity,
                    f.auto_fixable,
                )

        # upsert history row
        if health is not None:
            owner_row = await conn.fetchrow(
                "SELECT owner, repo FROM scans WHERE scan_id = $1", scan_id
            )
            if owner_row:
                await conn.execute(
                    """
                    INSERT INTO scan_history
                    (owner, repo, scan_id, scanned_at, overall, security, deps, quality, coverage)
                    VALUES ($1, $2, $3, NOW(), $4, $5, $6, $7, $8)
                    ON CONFLICT (owner, repo, scan_id) DO UPDATE SET
                        scanned_at = EXCLUDED.scanned_at,
                        overall = EXCLUDED.overall,
                        security = EXCLUDED.security,
                        deps = EXCLUDED.deps,
                        quality = EXCLUDED.quality,
                        coverage = EXCLUDED.coverage
                    """,
                    owner_row["owner"], owner_row["repo"], scan_id,
                    health.overall, health.security, health.dependencies,
                    health.code_quality, health.test_coverage,
                )


async def get_scan(scan_id: str) -> Optional[Dict[str, Any]]:
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM scans WHERE scan_id = $1", scan_id
        )
        if not row:
            return None
        return dict(row)


async def get_repo_history(owner: str, repo: str) -> List[Dict[str, Any]]:
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT scan_id, scanned_at, overall, security, deps, quality, coverage
            FROM scan_history
            WHERE owner = $1 AND repo = $2
            ORDER BY scanned_at DESC
            LIMIT 50
            """,
            owner, repo,
        )
        return [dict(r) for r in rows]


async def get_recent_scans(limit: int = 5) -> List[Dict[str, Any]]:
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT s.owner, s.repo, s.health_overall as score, s.scan_id, s.completed_at
            FROM (
                SELECT owner, repo, MAX(completed_at) as max_completed
                FROM scans
                WHERE status = 'completed' AND health_overall IS NOT NULL
                GROUP BY owner, repo
            ) latest
            JOIN scans s ON s.owner = latest.owner AND s.repo = latest.repo AND s.completed_at = latest.max_completed
            ORDER BY s.completed_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
