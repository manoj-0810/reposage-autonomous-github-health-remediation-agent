"""
RepoSage — OrchestratorAgent (Agent 6).
Manages the full Fetch → Audit → Prioritize → Fix → Action pipeline.
Streams status updates, handles per-agent errors gracefully, computes the
final HealthScore, and persists results to PostgreSQL.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Dict, List, Optional

from agents.action_agent import ActionAgent
from agents.audit_agent import AuditAgent
from agents.base import BaseAgent, emit_event
from agents.fetch_agent import FetchAgent
from agents.fix_agent import FixAgent
from agents.prioritizer_agent import PrioritizerAgent
from models.schemas import (
    AgentContext,
    AgentEvent,
    AgentResult,
    AgentStatus,
    HealthScore,
    ScanResult,
)

# ═══════════════════════════════════════════════════════════════════════════
# Health-score weights
# ═══════════════════════════════════════════════════════════════════════════
_WEIGHTS = {
    "security": 0.40,
    "dependencies": 0.25,
    "code_quality": 0.20,
    "test_coverage": 0.15,
}


class OrchestratorAgent(BaseAgent):
    """
    Agent 6 — OrchestratorAgent.

    Runs the complete pipeline end-to-end.  Each stage feeds its output
    into the shared :class:`AgentContext` so downstream agents can read it.
    Errors in any stage are logged but do **not** abort the pipeline.
    """

    name = "OrchestratorAgent"

    def __init__(
        self,
        on_event: Optional[Callable[[AgentEvent], None]] = None,
    ) -> None:
        super().__init__()
        self._on_event = on_event

    def _emit(self, ctx: AgentContext, status: AgentStatus, message: str,
              data: Optional[Dict[str, Any]] = None) -> None:
        event = AgentEvent(
            scan_id=ctx.scan_id,
            agent=self.name,
            status=status,
            message=message,
            data=data or {},
        )
        emit_event(event)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass

    def _compute_health_score(self, ctx: AgentContext) -> HealthScore:
        """Compute weighted health score from the prioritizer's breakdown."""
        if ctx.prioritized and ctx.prioritized.health_score_breakdown:
            bd = ctx.prioritized.health_score_breakdown
        else:
            bd = {k: 100.0 for k in _WEIGHTS}

        overall = sum(
            bd.get(k, 100.0) * w for k, w in _WEIGHTS.items()
        )
        return HealthScore(
            overall=round(max(0.0, min(100.0, overall)), 1),
            security=round(max(0.0, min(100.0, bd.get("security", 100.0))), 1),
            dependencies=round(max(0.0, min(100.0, bd.get("dependencies", 100.0))), 1),
            code_quality=round(max(0.0, min(100.0, bd.get("code_quality", 100.0))), 1),
            test_coverage=round(max(0.0, min(100.0, bd.get("test_coverage", 100.0))), 1),
        )

    async def run(self, context: AgentContext) -> AgentResult:
        ctx = context
        pipeline_start = time.perf_counter()

        self._emit(ctx, AgentStatus.RUNNING,
                   f"🚀 Starting RepoSage pipeline for {ctx.owner}/{ctx.repo}")

        # ── Stage 1: FetchAgent ──────────────────────────────────────────
        fetch = FetchAgent()
        fetch_result = await fetch.execute(ctx)
        if not fetch_result.success:
            self._emit(ctx, AgentStatus.ERROR,
                       f"FetchAgent failed: {fetch_result.error}")
            return AgentResult(success=False, error=fetch_result.error)

        # ── Stage 2: AuditAgent ──────────────────────────────────────────
        audit = AuditAgent()
        audit_result = await audit.execute(ctx)
        if not audit_result.success:
            self._emit(ctx, AgentStatus.ERROR,
                       f"AuditAgent failed: {audit_result.error} — continuing")

        # ── Stage 3: PrioritizerAgent ────────────────────────────────────
        prioritizer = PrioritizerAgent()
        prior_result = await prioritizer.execute(ctx)
        if not prior_result.success:
            self._emit(ctx, AgentStatus.ERROR,
                       f"PrioritizerAgent failed: {prior_result.error} — continuing")

        # compute health score now that we have breakdown
        ctx.health_score = self._compute_health_score(ctx)
        self._emit(ctx, AgentStatus.RUNNING,
                   f"Health score computed: {ctx.health_score.overall}/100",
                   data={"health_score": ctx.health_score.model_dump()})

        # ── Stage 4: FixAgent ────────────────────────────────────────────
        fix = FixAgent()
        fix_result = await fix.execute(ctx)
        if not fix_result.success:
            self._emit(ctx, AgentStatus.ERROR,
                       f"FixAgent failed: {fix_result.error} — continuing")

        # ── Stage 5: ActionAgent ─────────────────────────────────────────
        action = ActionAgent()
        action_result = await action.execute(ctx)
        if not action_result.success:
            self._emit(ctx, AgentStatus.ERROR,
                       f"ActionAgent failed: {action_result.error} — continuing")

        # ── Pipeline complete ────────────────────────────────────────────
        duration = round(time.perf_counter() - pipeline_start, 2)
        self._emit(ctx, AgentStatus.DONE,
                   f"✅ RepoSage pipeline complete in {duration}s — "
                   f"score {ctx.health_score.overall}/100",
                   data={
                       "health_score": ctx.health_score.model_dump(),
                       "findings": len(ctx.findings),
                       "patches": len(ctx.patches),
                   })

        return AgentResult(
            success=True,
            data={
                "health_score": ctx.health_score.model_dump(),
                "findings_count": len(ctx.findings),
                "patches_count": len(ctx.patches),
                "pipeline_duration_seconds": duration,
            },
        )
