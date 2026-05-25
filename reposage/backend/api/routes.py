"""
RepoSage — FastAPI routes.
  POST /api/scans          → kick off a scan
  GET  /api/scans/{id}     → get scan result
  GET  /api/scans/{id}/stream  → SSE real-time agent events
  GET  /api/repos/{owner}/{repo}/history  → health score history
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import db.database as db
from agents.base import register_event_emitter, unregister_event_emitter
from agents.orchestrator import OrchestratorAgent
from models.schemas import AgentContext, AgentEvent, ScanRequest, ScanResponse

router = APIRouter()

# In-memory queue per scan_id for SSE.
_event_queues: Dict[str, asyncio.Queue[AgentEvent]] = {}
# In-memory event history per scan_id to support replay on connect/reconnect.
_event_history: Dict[str, List[AgentEvent]] = {}


class ScanRequestBody(BaseModel):
    repo_url: str
    github_token: str


def _parse_repo_url(url: str) -> tuple[str, str]:
    """Extract owner/repo from a GitHub URL."""
    url = url.rstrip("/").replace("https://github.com/", "").replace("http://github.com/", "")
    parts = url.split("/")
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repo URL")
    return parts[0], parts[1]


def _parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


async def _run_pipeline(scan_id: str, repo_url: str, token: str) -> None:
    """Background task that runs the full agent pipeline."""
    owner, repo = _parse_repo_url(repo_url)

    import os
    effective_token = token.strip() if token else ""
    if not effective_token:
        effective_token = os.getenv("GITHUB_TOKEN", "")

    ctx = AgentContext(
        scan_id=scan_id,
        repo_url=repo_url,
        github_token=effective_token,
        owner=owner,
        repo=repo,
    )

    # Create DB record
    await db.create_scan(scan_id, repo_url, owner, repo)

    # wire event → queue so SSE clients receive it
    def _on_event(ev: AgentEvent) -> None:
        # Save to scan's event history list
        if scan_id not in _event_history:
            _event_history[scan_id] = []
        _event_history[scan_id].append(ev)

        q = _event_queues.get(ev.scan_id)
        if q:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    register_event_emitter(_on_event)
    try:
        orch = OrchestratorAgent(on_event=_on_event)
        result = await orch.run(ctx)

        # Persist final state
        actions_data = None
        if ctx.actions:
            actions_data = {
                "issues": [i.model_dump() for i in ctx.actions.issues],
                "pull_requests": [p.model_dump() for p in ctx.actions.pull_requests],
                "summary_issue_url": ctx.actions.summary_issue_url,
            }

        await db.update_scan_status(
            scan_id=scan_id,
            status="completed" if result.success else "error",
            health=ctx.health_score,
            findings=ctx.findings,
            patches=ctx.patches,
            actions=actions_data,
        )
    except Exception as exc:
        await db.update_scan_status(scan_id, "error")
        _on_event(AgentEvent(
            scan_id=scan_id,
            agent="OrchestratorAgent",
            status="error",
            message=str(exc),
        ))
    finally:
        unregister_event_emitter(_on_event)
        # sentinel so SSE knows to close
        q = _event_queues.get(scan_id)
        if q:
            q.put_nowait(None)  # type: ignore[arg-type]


# ── endpoints ────────────────────────────────────────────────────────────

@router.post("/api/scans", response_model=ScanResponse)
async def create_scan(body: ScanRequestBody) -> ScanResponse:
    scan_id = str(uuid.uuid4())
    _event_queues[scan_id] = asyncio.Queue(maxsize=500)
    asyncio.create_task(_run_pipeline(scan_id, body.repo_url, body.github_token))
    return ScanResponse(scan_id=scan_id, status="queued")


@router.get("/api/scans/recent")
async def get_recent_scans() -> List[Dict[str, Any]]:
    return await db.get_recent_scans(limit=10)


@router.get("/api/scans/{scan_id}")
async def get_scan(scan_id: str) -> Dict[str, Any]:
    row = await db.get_scan(scan_id)
    if not row:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {
        "scan_id": row["scan_id"],
        "repo_url": row["repo_url"],
        "owner": row["owner"],
        "repo": row["repo"],
        "status": row["status"],
        "health_score": {
            "overall": row["health_overall"],
            "security": row["health_security"],
            "dependencies": row["health_deps"],
            "code_quality": row["health_quality"],
            "test_coverage": row["health_coverage"],
        } if row["health_overall"] is not None else None,
        "findings": _parse_json(row["findings_json"]) or [],
        "patches": _parse_json(row["patches_json"]) or [],
        "actions": _parse_json(row["actions_json"]) or {"issues": [], "pull_requests": [], "summary_issue_url": None},
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


@router.get("/api/scans/{scan_id}/stream")
async def stream_scan(scan_id: str) -> StreamingResponse:
    # Get or create queue and history list
    history = _event_history.get(scan_id, [])
    q = _event_queues.get(scan_id)
    if q is None:
        q = asyncio.Queue(maxsize=500)
        _event_queues[scan_id] = q

    async def _event_generator() -> AsyncGenerator[str, None]:
        # 1. First yield all historical events that have run so far
        for event in list(history):
            payload = {
                "scan_id": event.scan_id,
                "agent": event.agent,
                "status": event.status.value,
                "message": event.message,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
            }
            yield f"data: {json.dumps(payload)}\n\n"

        # 2. Yield new events in real-time as they arrive
        while True:
            event = await q.get()
            if event is None:
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
            payload = {
                "scan_id": event.scan_id,
                "agent": event.agent,
                "status": event.status.value,
                "message": event.message,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
            }
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/repos/{owner}/{repo}/history")
async def repo_history(owner: str, repo: str) -> List[Dict[str, Any]]:
    rows = await db.get_repo_history(owner, repo)
    return [
        {
            "scan_id": r["scan_id"],
            "scanned_at": r["scanned_at"].isoformat() if r["scanned_at"] else None,
            "health_score": r["overall"],
            "security": r["security"],
            "dependencies": r["deps"],
            "code_quality": r["quality"],
            "test_coverage": r["coverage"],
        }
        for r in rows
    ]
