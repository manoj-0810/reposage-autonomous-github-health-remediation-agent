"""
RepoSage — BaseAgent interface.
Every agent in the pipeline inherits from this class for a uniform contract.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from models.schemas import AgentContext, AgentEvent, AgentResult, AgentStatus

# Global callback registry for SSE streaming — populated by the Orchestrator.
_event_emitters: List[Callable[[AgentEvent], None]] = []


def register_event_emitter(fn: Callable[[AgentEvent], None]) -> None:
    """Subscribe a callback to receive every AgentEvent emitted by any agent."""
    _event_emitters.append(fn)


def unregister_event_emitter(fn: Callable[[AgentEvent], None]) -> None:
    """Remove a previously-subscribed callback."""
    if fn in _event_emitters:
        _event_emitters.remove(fn)


def emit_event(event: AgentEvent) -> None:
    """Broadcast an event to all registered emitters (e.g., SSE streams)."""
    for fn in _event_emitters:
        try:
            fn(event)
        except Exception:
            pass  # Never let a broken emitter crash an agent.


class BaseAgent(ABC):
    """
    Abstract base class for all RepoSage agents.

    Subclasses must implement ``run`` and may override ``_emit`` to customize
    event broadcasting.  The base implementation automatically records
    start/end timing and token consumption.
    """

    name: str = "BaseAgent"

    def __init__(self) -> None:
        self._tokens_used: int = 0
        self._start_time: float = 0.0

    # ── internal helpers ──────────────────────────────────────────────────

    def _emit(self, ctx: AgentContext, status: AgentStatus, message: str,
              data: Optional[Dict[str, Any]] = None) -> None:
        """Helper that builds an AgentEvent and broadcasts it."""
        event = AgentEvent(
            scan_id=ctx.scan_id,
            agent=self.name,
            status=status,
            message=message,
            data=data or {},
        )
        emit_event(event)

    def _track_tokens(self, n: int) -> None:
        """Accumulate LLM token usage so it can be reported in AgentResult."""
        self._tokens_used += n

    # ── public contract ───────────────────────────────────────────────────

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """
        Execute the agent's logic.

        Parameters
        ----------
        context:
            Shared mutable context containing the repo snapshot, findings,
            and any intermediate artifacts produced by upstream agents.

        Returns
        -------
        AgentResult:
            Structured result with success flag, optional data payload,
            timing info, and token usage.
        """
        ...

    async def execute(self, context: AgentContext) -> AgentResult:
        """
        Wrapper around ``run`` that adds lifecycle instrumentation:
        emits *pending*, *running*, *done*/*error* events and captures
        wall-clock duration.
        """
        self._tokens_used = 0
        self._start_time = time.perf_counter()
        self._emit(context, AgentStatus.PENDING, f"{self.name} queued")
        self._emit(context, AgentStatus.RUNNING, f"{self.name} started")

        try:
            result = await self.run(context)
            result.agent_name = self.name
            result.duration_seconds = round(time.perf_counter() - self._start_time, 2)
            result.tokens_used = self._tokens_used
            self._emit(
                context,
                AgentStatus.DONE,
                f"{self.name} finished in {result.duration_seconds}s",
                data={"success": result.success, "tokens_used": result.tokens_used},
            )
            return result
        except Exception as exc:
            duration = round(time.perf_counter() - self._start_time, 2)
            self._emit(
                context,
                AgentStatus.ERROR,
                f"{self.name} failed: {exc}",
                data={"error": str(exc)},
            )
            return AgentResult(
                success=False,
                agent_name=self.name,
                error=str(exc),
                duration_seconds=duration,
                tokens_used=self._tokens_used,
            )
