"""
RepoSage — pytest suite.
Each agent has at least one happy-path test with a mocked GitAgent / LLM layer.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the backend package is importable
os.environ.setdefault("KIMI_API_KEY", "test-kimi-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from agents.action_agent import ActionAgent
from agents.audit_agent import AuditAgent
from agents.fetch_agent import FetchAgent
from agents.fix_agent import FixAgent
from agents.orchestrator import OrchestratorAgent
from agents.prioritizer_agent import PrioritizerAgent
from models.schemas import (
    AgentContext,
    AgentResult,
    AuditFinding,
    CommitInfo,
    FindingCategory,
    HealthScore,
    RepoSnapshot,
    Severity,
)


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(
        scan_id="test-scan-001",
        repo_url="https://github.com/test-org/test-repo",
        github_token="ghp_testtoken",
        owner="test-org",
        repo="test-repo",
    )


@pytest.fixture
def snapshot() -> RepoSnapshot:
    return RepoSnapshot(
        owner="test-org",
        repo="test-repo",
        default_branch="main",
        file_tree=[
            "src/main.py",
            "src/utils.py",
            "tests/test_main.py",
            "package.json",
            "README.md",
            ".github/workflows/ci.yml",
        ],
        manifests={
            "package.json": json.dumps({
                "dependencies": {"lodash": "4.17.0", "express": "4.16.0"},
                "devDependencies": {"jest": "26.0.0"},
            }),
        },
        recent_commits=[
            CommitInfo(
                sha="abc123", message="feat: initial", author="dev",
                date=datetime.utcnow(), files_changed=["src/main.py"],
            ),
            CommitInfo(
                sha="def456", message="fix: bug", author="dev",
                date=datetime.utcnow(), files_changed=["src/main.py", "src/utils.py"],
            ),
        ],
        open_prs=[],
        readme="# Test Repo\nA test repository.",
        ci_config={".github/workflows/ci.yml": "name: CI\non: push\n"},
        language="Python",
        stars=42,
        forks=7,
    )


# ── FetchAgent tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_agent_happy_path(ctx: AgentContext, snapshot: RepoSnapshot):
    """FetchAgent should build a RepoSnapshot from GitHub API responses."""
    agent = FetchAgent()

    # Mock all GitHub API calls
    mock_tree = {"tree": [
        {"path": "src/main.py", "type": "blob"},
        {"path": "package.json", "type": "blob"},
        {"path": "README.md", "type": "blob"},
    ]}
    mock_repo = {"default_branch": "main", "language": "Python", "stargazers_count": 42, "forks_count": 7}
    mock_commits = [{"sha": "abc", "commit": {"message": "init", "author": {"name": "dev", "date": "2024-01-01T00:00:00Z"}}}]
    mock_prs = []

    async def _mock_get(url: str, headers: Dict[str, str]) -> Any:
        if "git/trees" in url:
            return mock_tree
        if "commits" in url:
            return mock_commits
        if "pulls" in url:
            return mock_prs
        return mock_repo

    async def _mock_file(owner: str, repo: str, path: str, headers: Dict[str, str]) -> Optional[str]:
        contents = {"package.json": '{"name": "test"}', "README.md": "# Test"}
        return contents.get(path)

    with patch.object(agent, "_get", new=_mock_get), \
         patch.object(agent, "_fetch_file_content", new=_mock_file):
        result = await agent.run(ctx)

    assert result.success
    assert ctx.snapshot is not None
    assert ctx.snapshot.owner == "test-org"
    assert ctx.snapshot.repo == "test-repo"
    assert "package.json" in ctx.snapshot.manifests


# ── AuditAgent tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_agent_happy_path(ctx: AgentContext, snapshot: RepoSnapshot):
    """AuditAgent should run 4 sub-audits and return merged findings."""
    ctx.snapshot = snapshot
    agent = AuditAgent()

    # Mock LLM calls to return valid JSON
    dep_response = json.dumps([{
        "package_name": "lodash", "current_version": "4.17.0",
        "issue_type": "outdated", "severity": "high",
        "description": "lodash is outdated", "suggested_fix": "bump to 4.17.21",
        "fix_complexity": 1,
    }])
    smell_response = json.dumps([{
        "file_path": "src/main.py", "line_start": 10, "line_end": 15,
        "issue_type": "dead_code", "severity": "medium",
        "description": "unused function", "suggested_fix": "remove it",
        "fix_complexity": 1, "auto_fixable": True,
    }])
    coverage_response = json.dumps({
        "estimated_coverage_percent": 35.0,
        "gaps": [{"module": "src/utils.py", "has_tests": False, "test_file_path": None, "missing_scenarios": ["edge cases"]}],
        "recommendations": ["Add tests for src/utils.py"],
    })
    security_response = json.dumps([{
        "file_path": "src/main.py", "line_start": 5, "line_end": 5,
        "issue_type": "eval_usage", "severity": "critical",
        "description": "eval() found", "suggested_fix": "use ast.literal_eval",
        "fix_complexity": 2, "auto_fixable": True,
    }])

    call_count = 0
    async def _mock_llm(prompt: str, model: str = "gemini-flash") -> str:
        nonlocal call_count
        call_count += 1
        if "dependency" in prompt.lower() or "manifest" in prompt.lower():
            return dep_response
        if "code review" in prompt.lower() or "smell" in prompt.lower():
            return smell_response
        if "coverage" in prompt.lower():
            return coverage_response
        return security_response

    with patch("agents.audit_agent._call_llm", new=_mock_llm):
        result = await agent.run(ctx)

    assert result.success
    assert len(ctx.findings) >= 3
    categories = {f.category for f in ctx.findings}
    assert FindingCategory.DEPENDENCIES in categories
    assert FindingCategory.SECURITY in categories


# ── PrioritizerAgent tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prioritizer_agent_happy_path(ctx: AgentContext):
    """PrioritizerAgent should rank findings and produce themes."""
    ctx.findings = [
        AuditFinding(
            category=FindingCategory.SECURITY, severity=Severity.CRITICAL,
            file_path="src/auth.py", line_range=(10, 20),
            description="SQL injection", suggested_fix="use params", fix_complexity=2, auto_fixable=True,
        ),
        AuditFinding(
            category=FindingCategory.DEPENDENCIES, severity=Severity.HIGH,
            file_path="package.json", description="outdated dep", suggested_fix="bump version", fix_complexity=1, auto_fixable=True,
        ),
        AuditFinding(
            category=FindingCategory.CODE_QUALITY, severity=Severity.LOW,
            file_path="src/main.py", description="long line", fix_complexity=1, auto_fixable=False,
        ),
    ]
    agent = PrioritizerAgent()

    with patch.object(agent, "_llm_blast_radius", return_value={0: 5, 1: 3, 2: 1}):
        result = await agent.run(ctx)

    assert result.success
    assert ctx.prioritized is not None
    assert len(ctx.prioritized.top_findings) <= 10
    # Critical security should be first
    assert ctx.prioritized.top_findings[0].severity == Severity.CRITICAL
    assert "security" in ctx.prioritized.health_score_breakdown


# ── FixAgent tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fix_agent_happy_path(ctx: AgentContext):
    """FixAgent should generate patches for auto-fixable findings."""
    ctx.prioritized = MagicMock()
    ctx.prioritized.top_findings = [
        AuditFinding(
            category=FindingCategory.SECURITY, severity=Severity.CRITICAL,
            file_path="src/auth.py", line_range=(10, 12),
            description="eval usage", suggested_fix="use literal_eval",
            fix_complexity=2, auto_fixable=True,
        ),
        AuditFinding(
            category=FindingCategory.CODE_QUALITY, severity=Severity.MEDIUM,
            file_path="src/old.py", line_range=(5, 8),
            description="dead code", suggested_fix="delete block",
            fix_complexity=1, auto_fixable=True,
        ),
    ]
    agent = FixAgent()

    patch_text = (
        "--- a/src/auth.py\n"
        "+++ b/src/auth.py\n"
        "@@ -10,3 +10,3 @@\n"
        "-result = eval(user_input)\n"
        "+result = ast.literal_eval(user_input)\n"
    )

    with patch.object(agent, "_generate_patch", return_value=patch_text):
        result = await agent.run(ctx)

    assert result.success
    assert len(ctx.patches) == 2
    assert all(p.patch.startswith("---") for p in ctx.patches)


# ── ActionAgent tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_action_agent_happy_path(ctx: AgentContext):
    """ActionAgent should create issues and PRs via the GitHub API."""
    ctx.prioritized = MagicMock()
    ctx.prioritized.top_findings = [
        AuditFinding(
            category=FindingCategory.SECURITY, severity=Severity.CRITICAL,
            file_path="src/auth.py", line_range=(10, 12),
            description="SQL injection", suggested_fix="parametrize",
            fix_complexity=2, auto_fixable=False,
        ),
    ]
    ctx.patches = []
    ctx.health_score = HealthScore(overall=65, security=40, dependencies=80, code_quality=70, test_coverage=60)
    ctx.snapshot = RepoSnapshot(owner="test-org", repo="test-repo", default_branch="main")

    agent = ActionAgent()

    mock_issue_resp = {"html_url": "https://github.com/test-org/test-repo/issues/1", "number": 1}
    mock_summary_resp = {"html_url": "https://github.com/test-org/test-repo/issues/99", "number": 99}

    call_count = 0
    async def _mock_post(self, url: str, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "issues" in url:
            resp.json.return_value = mock_issue_resp if call_count < 5 else mock_summary_resp
        else:
            resp.json.return_value = {"html_url": "https://github.com/test-org/test-repo/pull/1", "number": 1}
        return resp

    async def _mock_get(self, url: str, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "git/ref" in url:
            resp.json.return_value = {"object": {"sha": "base-sha"}}
        elif "contents" in url:
            resp.json.return_value = {"content": "cHJpbnQoImhlbGxvIik=", "sha": "file-sha"}
        else:
            resp.json.return_value = {}
        return resp

    with patch("httpx.AsyncClient.post", new=_mock_post), \
         patch("httpx.AsyncClient.get", new=_mock_get):
        result = await agent.run(ctx)

    assert result.success
    assert result.data["issues"] >= 1


# ── OrchestratorAgent tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_happy_path(ctx: AgentContext, snapshot: RepoSnapshot):
    """Orchestrator should run the full pipeline and compute a health score."""
    ctx.snapshot = snapshot
    ctx.findings = [
        AuditFinding(
            category=FindingCategory.SECURITY, severity=Severity.CRITICAL,
            file_path="src/auth.py", line_range=(1, 5),
            description="eval found", suggested_fix="remove eval", fix_complexity=2, auto_fixable=True,
        ),
        AuditFinding(
            category=FindingCategory.DEPENDENCIES, severity=Severity.HIGH,
            file_path="package.json", description="old lodash", suggested_fix="bump", fix_complexity=1, auto_fixable=True,
        ),
    ]

    async def _mock_execute(self, context: AgentContext) -> AgentResult:
        return AgentResult(success=True, agent_name=self.name)

    with patch("agents.fetch_agent.FetchAgent.execute", new=_mock_execute), \
         patch("agents.audit_agent.AuditAgent.execute", new=_mock_execute), \
         patch("agents.prioritizer_agent.PrioritizerAgent.execute", new=_mock_execute), \
         patch("agents.fix_agent.FixAgent.execute", new=_mock_execute), \
         patch("agents.action_agent.ActionAgent.execute", new=_mock_execute):
        orch = OrchestratorAgent()
        result = await orch.run(ctx)

    assert result.success
    assert ctx.health_score is not None
    assert 0 <= ctx.health_score.overall <= 100
    assert result.data["findings_count"] == 2


@pytest.mark.asyncio
async def test_orchestrator_graceful_failure(ctx: AgentContext):
    """Orchestrator should handle missing snapshot gracefully."""
    async def _mock_fetch_fail(self, context: AgentContext) -> AgentResult:
        return AgentResult(success=False, agent_name="FetchAgent", error="No repo snapshot available.")

    with patch("agents.fetch_agent.FetchAgent.execute", new=_mock_fetch_fail):
        orch = OrchestratorAgent()
        result = await orch.run(ctx)
        assert not result.success
        assert "snapshot" in result.error.lower() or result.error
