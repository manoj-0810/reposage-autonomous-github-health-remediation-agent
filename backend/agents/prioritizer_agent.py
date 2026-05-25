"""
RepoSage — PrioritizerAgent (Agent 3).
Scores each AuditFinding by severity × blast_radius / fix_complexity,
groups related findings into themes, and returns the top 10.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from agents.base import BaseAgent
from models.schemas import (
    AgentContext,
    AgentResult,
    AgentStatus,
    AuditFinding,
    FindingCategory,
    FindingTheme,
    PrioritizedResult,
    Severity,
)

_PROMPT = """
You are a technical prioritization engine. Given the following audit findings,
score each by blast_radius (1-5) and provide a 2-sentence theme grouping.

Findings (JSON):
{findings_json}

Respond ONLY with a JSON object:
{{
  "scores": [
    {{"index": int, "blast_radius": int(1-5), "theme": str}}
  ],
  "theme_names": [str]
}}
"""


class PrioritizerAgent(BaseAgent):
    """
    Agent 3 — PrioritizerAgent.

    1. Uses Groq Llama 3.3 to estimate blast radius for each finding.
    2. Computes priority_score = severity_weight × blast_radius / fix_complexity.
    3. Groups by directory/theme.
    4. Returns top-10 findings + theme groups.
    """

    name = "PrioritizerAgent"

    # severity numeric weights
    _SEV_WEIGHT = {
        Severity.CRITICAL: 10.0,
        Severity.HIGH: 6.0,
        Severity.MEDIUM: 3.0,
        Severity.LOW: 1.0,
    }

    async def _llm_blast_radius(self, findings: List[AuditFinding]) -> Dict[int, int]:
        """Ask Groq Llama 3.3 for blast-radius estimates."""
        if not findings:
            return {}
        import os
        import httpx
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            # fallback: heuristic based on category (no GROQ_API_KEY set)
            return {i: 3 for i in range(len(findings))}

        # slim JSON to fit context window
        slim = []
        for i, f in enumerate(findings):
            slim.append({
                "index": i,
                "category": f.category.value,
                "severity": f.severity.value,
                "file": f.file_path,
                "desc": f.description[:200],
            })

        prompt = _PROMPT.format(findings_json=json.dumps(slim[:50]))
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
            content = data["choices"][0]["message"].get("content", "{}")
            # extract JSON
            import re as _re
            m = _re.search(r'\{.*\}', content, _re.DOTALL)
            if not m:
                return {i: 3 for i in range(len(findings))}
            obj = json.loads(m.group())
            scores = {}
            for entry in obj.get("scores", []):
                scores[entry["index"]] = entry.get("blast_radius", 3)
            return scores
        except Exception:
            return {i: 3 for i in range(len(findings))}

    async def run(self, context: AgentContext) -> AgentResult:
        if not context.findings:
            context.prioritized = PrioritizedResult(
                top_findings=[],
                themes=[],
                health_score_breakdown={
                    "security": 100.0,
                    "dependencies": 100.0,
                    "code_quality": 100.0,
                    "test_coverage": 100.0,
                },
            )
            return AgentResult(success=True, data={"top_n": 0})

        findings = context.findings
        self._emit(context, AgentStatus.RUNNING,
                   f"Prioritizing {len(findings)} findings …")

        # 1. get blast radius from LLM
        blast_map = await self._llm_blast_radius(findings)

        # 2. compute priority score for each
        scored: List[Tuple[float, AuditFinding, int]] = []
        for idx, f in enumerate(findings):
            sev_w = self._SEV_WEIGHT.get(f.severity, 1.0)
            br = blast_map.get(idx, 3)
            complexity = max(1, f.fix_complexity)
            score = sev_w * br / complexity
            scored.append((score, f, idx))

        # 3. sort descending
        scored.sort(key=lambda x: x[0], reverse=True)
        top_findings = [f for _, f, _ in scored[:10]]

        # 4. compute health score breakdown (0=terrible, 100=perfect)
        breakdown: Dict[str, float] = {}
        for cat in FindingCategory:
            cat_findings = [f for f in findings if f.category == cat]
            if not cat_findings:
                breakdown[cat.value] = 100.0
                continue
            # weighted average: critical=10pts off, high=6, medium=3, low=1
            penalty = sum(
                self._SEV_WEIGHT.get(f.severity, 1.0) * 2.5
                for f in cat_findings
            )
            breakdown[cat.value] = max(0.0, 100.0 - penalty)

        # 5. group themes by directory prefix
        dir_groups: Dict[str, List[AuditFinding]] = defaultdict(list)
        for f in top_findings:
            parts = f.file_path.split("/")
            prefix = parts[0] if len(parts) <= 2 else "/".join(parts[:2])
            dir_groups[prefix].append(f)

        themes: List[FindingTheme] = []
        for prefix, group in sorted(dir_groups.items(), key=lambda x: -len(x[1])):
            max_sev = max((f.severity for f in group), key=lambda s: self._SEV_WEIGHT.get(s, 0))
            agg_score = sum(
                self._SEV_WEIGHT.get(f.severity, 1) for f in group
            )
            themes.append(FindingTheme(
                title=f"{len(group)} issues in {prefix}/",
                findings=group,
                aggregate_severity=max_sev,
                priority_score=agg_score,
            ))

        context.prioritized = PrioritizedResult(
            top_findings=top_findings,
            themes=themes,
            health_score_breakdown=breakdown,
        )

        self._emit(context, AgentStatus.DONE,
                   f"Prioritization complete — top {len(top_findings)} findings, {len(themes)} themes",
                   data={"top_n": len(top_findings), "themes": len(themes)})

        return AgentResult(
            success=True,
            data={
                "top_n": len(top_findings),
                "themes": len(themes),
                "breakdown": breakdown,
            },
        )
