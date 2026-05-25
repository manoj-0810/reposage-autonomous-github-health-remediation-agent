"""
RepoSage — FixAgent (Agent 4).
Generates syntactically-valid unified-diff patches for auto-fixable findings
using Groq Llama 3.3.  Each patch is validated before being returned.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from models.schemas import AgentContext, AgentResult, AgentStatus, AuditFinding, CodePatch

_PROMPT = """
You are an expert software engineer. Given the following code issue,
generate a unified diff patch (``diff -u`` format) that fixes it.

The patch must:
1. Be a valid unified diff with --- and +++ headers
2. Include @@ hunk headers
3. Only modify the specific lines related to the issue
4. Preserve all surrounding code exactly

Issue:
  file: {file_path}
  lines: {line_range}
  description: {description}
  suggested_fix: {suggested_fix}

Respond ONLY with the raw diff patch (no markdown fences, no explanation).
If you cannot generate a valid patch, reply with exactly: UNFIXABLE
"""


class FixAgent(BaseAgent):
    """
    Agent 4 — FixAgent.

    Iterates over auto-fixable findings, asks Groq Llama 3.3 for a patch,
    performs lightweight syntactic validation, and returns validated patches.
    """

    name = "FixAgent"

    def _is_auto_fixable(self, finding: AuditFinding) -> bool:
        """Heuristic: can we auto-generate a patch for this?"""
        if not finding.auto_fixable:
            return False
        if finding.fix_complexity > 3:
            return False
        # We can't patch without knowing the line range
        if finding.line_range is None:
            return False
        return True

    async def _generate_patch(self, finding: AuditFinding) -> Optional[str]:
        import os
        import httpx
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            return None

        line_range_str = f"{finding.line_range[0]}-{finding.line_range[1]}" if finding.line_range else "unknown"
        prompt = _PROMPT.format(
            file_path=finding.file_path,
            line_range=line_range_str,
            description=finding.description,
            suggested_fix=finding.suggested_fix or "Apply best-practice fix",
        )
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, json=body, headers=headers)
                r.raise_for_status()
                data = r.json()
            content = data["choices"][0]["message"].get("content", "")
            content = content.strip()
            if content == "UNFIXABLE":
                return None
            if content.startswith("```diff"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            if not content.startswith("---"):
                # Wrap in a minimal diff header if the model omitted it
                content = (
                    f"--- a/{finding.file_path}\n"
                    f"+++ b/{finding.file_path}\n"
                    f"{content}"
                )
            return content
        except Exception:
            return None

    def _validate_patch(self, patch: str, file_path: str) -> bool:
        """Lightweight validation: must have ---, +++, and @@ headers."""
        has_minus = any(line.startswith("---") for line in patch.splitlines())
        has_plus = any(line.startswith("+++") for line in patch.splitlines())
        has_hunk = "@@" in patch
        return has_minus and has_plus and has_hunk

    async def run(self, context: AgentContext) -> AgentResult:
        if not context.prioritized:
            return AgentResult(success=False, error="No prioritized findings to fix.")

        findings = context.prioritized.top_findings
        auto_fixable = [f for f in findings if self._is_auto_fixable(f)]

        self._emit(context, AgentStatus.RUNNING,
                   f"Generating patches for {len(auto_fixable)} auto-fixable findings …")

        patches: List[CodePatch] = []
        for idx, finding in enumerate(auto_fixable):
            self._emit(context, AgentStatus.RUNNING,
                       f"Generating patch for {finding.file_path} …")
            patch_text = await self._generate_patch(finding)
            if patch_text and self._validate_patch(patch_text, finding.file_path):
                patches.append(CodePatch(
                    target_file=finding.file_path,
                    patch=patch_text,
                    description=finding.suggested_fix or finding.description,
                    finding_index=findings.index(finding),
                ))
                self._emit(context, AgentStatus.RUNNING,
                           f"Patch validated for {finding.file_path}")
            else:
                self._emit(context, AgentStatus.RUNNING,
                           f"Could not auto-fix {finding.file_path}")

        context.patches = patches

        self._emit(context, AgentStatus.DONE,
                   f"Fix generation complete — {len(patches)} valid patches",
                   data={"patches": len(patches)})

        return AgentResult(
            success=True,
            data={"patches": len(patches)},
        )
