"""
RepoSage — Pydantic schemas for the entire multi-agent pipeline.
Every data shape flowing between agents is defined here for full type safety.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


# ═══════════════════════════════════════════════════════════════════════════
# Enumerations
# ═══════════════════════════════════════════════════════════════════════════

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingCategory(str, Enum):
    SECURITY = "security"
    DEPENDENCIES = "dependencies"
    CODE_QUALITY = "code_quality"
    TEST_COVERAGE = "test_coverage"


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# ═══════════════════════════════════════════════════════════════════════════
# Repo Snapshot (output of FetchAgent)
# ═══════════════════════════════════════════════════════════════════════════

class RepoFile(BaseModel):
    path: str
    size: int
    content: Optional[str] = None
    is_binary: bool = False


class CommitInfo(BaseModel):
    sha: str
    message: str
    author: str
    date: datetime
    files_changed: List[str] = Field(default_factory=list)


class PullRequestInfo(BaseModel):
    number: int
    title: str
    author: str
    state: str
    created_at: datetime
    updated_at: datetime


class RepoSnapshot(BaseModel):
    owner: str
    repo: str
    default_branch: str = "main"
    file_tree: List[str] = Field(default_factory=list)
    files: Dict[str, RepoFile] = Field(default_factory=dict)
    manifests: Dict[str, str] = Field(default_factory=dict)   # path -> content
    recent_commits: List[CommitInfo] = Field(default_factory=list)
    open_prs: List[PullRequestInfo] = Field(default_factory=list)
    readme: Optional[str] = None
    ci_config: Dict[str, str] = Field(default_factory=dict)   # path -> content
    language: Optional[str] = None
    stars: int = 0
    forks: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Audit Findings (output of AuditAgent)
# ═══════════════════════════════════════════════════════════════════════════

class AuditFinding(BaseModel):
    category: FindingCategory
    severity: Severity
    file_path: str
    line_range: Optional[tuple[int, int]] = None
    description: str
    suggested_fix: Optional[str] = None
    raw_evidence: Optional[str] = None  # snippet / matched text
    fix_complexity: int = Field(default=3, ge=1, le=5,
                                 description="1=simple, 5=hard")
    auto_fixable: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Prioritized Finding Theme (output of PrioritizerAgent)
# ═══════════════════════════════════════════════════════════════════════════

class FindingTheme(BaseModel):
    title: str
    findings: List[AuditFinding]
    aggregate_severity: Severity
    priority_score: float


class PrioritizedResult(BaseModel):
    top_findings: List[AuditFinding]
    themes: List[FindingTheme]
    health_score_breakdown: Dict[str, float]  # per-dimension 0-100


# ═══════════════════════════════════════════════════════════════════════════
# Code Patch (output of FixAgent)
# ═══════════════════════════════════════════════════════════════════════════

class CodePatch(BaseModel):
    target_file: str
    patch: str  # unified diff format
    description: str
    finding_index: int  # index into top_findings


# ═══════════════════════════════════════════════════════════════════════════
# GitHub Action Result (output of ActionAgent)
# ═══════════════════════════════════════════════════════════════════════════

class CreatedIssue(BaseModel):
    title: str
    url: str
    number: int
    labels: List[str] = Field(default_factory=list)


class CreatedPullRequest(BaseModel):
    title: str
    url: str
    number: int
    branch: str
    linked_issue_number: Optional[int] = None


class ActionResult(BaseModel):
    issues: List[CreatedIssue] = Field(default_factory=list)
    pull_requests: List[CreatedPullRequest] = Field(default_factory=list)
    summary_issue_url: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Health Score
# ═══════════════════════════════════════════════════════════════════════════

class HealthScore(BaseModel):
    overall: float = Field(ge=0, le=100)
    security: float = Field(ge=0, le=100)
    dependencies: float = Field(ge=0, le=100)
    code_quality: float = Field(ge=0, le=100)
    test_coverage: float = Field(ge=0, le=100)


# ═══════════════════════════════════════════════════════════════════════════
# Agent Event (SSE payload)
# ═══════════════════════════════════════════════════════════════════════════

class AgentEvent(BaseModel):
    scan_id: str
    agent: str
    status: AgentStatus
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════════════
# Agent Context & Result (shared interface)
# ═══════════════════════════════════════════════════════════════════════════

class AgentContext(BaseModel):
    scan_id: str
    repo_url: str
    github_token: str
    owner: str
    repo: str
    snapshot: Optional[RepoSnapshot] = None
    findings: List[AuditFinding] = Field(default_factory=list)
    prioritized: Optional[PrioritizedResult] = None
    patches: List[CodePatch] = Field(default_factory=list)
    actions: Optional[ActionResult] = None
    health_score: Optional[HealthScore] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    success: bool
    agent_name: str = ""
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    tokens_used: Optional[int] = None


# ═══════════════════════════════════════════════════════════════════════════
# Scan Request / Response
# ═══════════════════════════════════════════════════════════════════════════

class ScanRequest(BaseModel):
    repo_url: HttpUrl
    github_token: str


class ScanResponse(BaseModel):
    scan_id: str
    status: str = "queued"


class ScanResult(BaseModel):
    scan_id: str
    repo_url: str
    owner: str
    repo: str
    status: str
    health_score: Optional[HealthScore] = None
    findings: List[AuditFinding] = Field(default_factory=list)
    prioritized: Optional[PrioritizedResult] = None
    patches: List[CodePatch] = Field(default_factory=list)
    actions: Optional[ActionResult] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════════════
# History Entry
# ═══════════════════════════════════════════════════════════════════════════

class HistoryEntry(BaseModel):
    scan_id: str
    scanned_at: datetime
    health_score: float
    security: float
    dependencies: float
    code_quality: float
    test_coverage: float
