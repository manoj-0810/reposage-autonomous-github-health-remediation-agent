"""
RepoSage — AuditAgent (Agent 2).
Runs 4 parallel sub-audits via ``asyncio.gather``:
  A. DependencyAuditor  — outdated / vulnerable packages
  B. CodeSmellDetector  — dead code, god classes, missing error handling, secrets, TODO bombs
  C. TestCoverageAnalyzer — structural coverage gaps
  D. SecurityScanner    — eval, exec, SQL injection, exposed credentials

Each sub-agent returns ``List[AuditFinding]``.  The AuditAgent merges,
deduplicates, and attaches results to the shared context.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from agents.base import BaseAgent
from models.schemas import (
    AgentContext,
    AgentResult,
    AgentStatus,
    AuditFinding,
    CommitInfo,
    FindingCategory,
    RepoSnapshot,
    Severity,
)

# ═══════════════════════════════════════════════════════════════════════════
# Prompts for LLM sub-agents (Kimi K2 / Gemini Flash)
# ═══════════════════════════════════════════════════════════════════════════

_DEPENDENCY_PROMPT = """
You are a dependency security auditor. Analyze the following manifest files
from a GitHub repository and identify outdated, vulnerable, or problematic
dependencies.

Manifests:
{manifests}

Respond ONLY with a JSON array of findings. Each finding must have:
  - package_name (str)
  - current_version (str)
  - issue_type (one of: "outdated", "vulnerable", "deprecated", "version_conflict")
  - severity (one of: "critical", "high", "medium", "low")
  - description (str)
  - suggested_fix (str, optional)
  - fix_complexity (int 1-5)

If no issues are found, return an empty array [].
"""

_CODE_SMELL_PROMPT = """
You are a senior software engineer performing a code review. Analyze the
following code files from a repository and detect:
1. Dead / unreachable code
2. God classes or functions that are too long
3. Missing error handling (bare except, no try/catch around risky ops)
4. Hardcoded secrets or API keys
5. "TODO bomb" comments indicating unfinished critical work

Files:
{files}

Respond ONLY with a JSON array of findings. Each finding must have:
  - file_path (str)
  - line_start (int)
  - line_end (int)
  - issue_type (str)
  - severity (one of: "critical", "high", "medium", "low")
  - description (str)
  - suggested_fix (str, optional)
  - fix_complexity (int 1-5)
  - auto_fixable (bool)

If no issues are found, return an empty array [].
"""

_TEST_COVERAGE_PROMPT = """
You are a test-coverage analyst. Given a repository's file tree and the
provided test files, estimate structural coverage gaps by comparing source
files to test files.

File tree:
{file_tree}

Source code files (sample):
{source_files}

Test files found:
{test_files}

Respond ONLY with a JSON object:
{{
  "estimated_coverage_percent": float,
  "gaps": [
    {{
      "module": str,
      "has_tests": bool,
      "test_file_path": str or null,
      "missing_scenarios": [str]
    }}
  ],
  "recommendations": [str]
}}
"""

_SECURITY_PROMPT = """
You are an application security engineer. Analyze the following code snippets
and identify security vulnerabilities such as:
- Use of eval() or exec()
- SQL string concatenation / injection
- Unvalidated user input
- Exposed credentials patterns (API keys, passwords, tokens)
- Insecure deserialization
- Path traversal risks
- Weak crypto patterns

Code snippets:
{snippets}

Respond ONLY with a JSON array of findings. Each finding must have:
  - file_path (str)
  - line_start (int)
  - line_end (int)
  - issue_type (str)
  - severity (one of: "critical", "high", "medium", "low")
  - description (str)
  - suggested_fix (str, optional)
  - fix_complexity (int 1-5)
  - auto_fixable (bool)

If no issues are found, return an empty array [].
"""


# ═══════════════════════════════════════════════════════════════════════════
# LLM helper (unified interface — swaps backend via env var)
# ═══════════════════════════════════════════════════════════════════════════

async def _call_llm(prompt: str, model: str = "gemini-flash") -> str:
    """
    Route to the appropriate LLM backend.
    * ``gemini-flash`` → Gemini 2.5 Flash (fast triage)
    * ``kimi-k2``       → Kimi K2 (deep analysis)
    """
    if model == "gemini-flash":
        return await _call_gemini_flash(prompt)
    return await _call_kimi_k2(prompt)


async def _call_gemini_flash(prompt: str) -> str:
    import os
    import httpx
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return "[]"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-preview-04-17:generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return "[]"
    return candidates[0]["content"]["parts"][0].get("text", "[]")


async def _call_kimi_k2(prompt: str) -> str:
    import os
    import httpx
    api_key = os.getenv("KIMI_API_KEY", "")
    if not api_key:
        return "[]"
    url = "https://api.moonshot.cn/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": "kimi-k2",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"].get("content", "[]")


def _extract_json(text: str) -> str:
    """Naïve but robust JSON extraction from an LLM response."""
    text = text.strip()
    # Handle markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    # Find first '[' or '{'
    text = text.strip()
    start = -1
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            start = i
            break
    if start == -1:
        return "[]"
    # Match brackets
    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] in ("[", "{"):
            depth += 1
        elif text[i] in ("]", "}"):
            depth -= 1
            if depth == 0:
                end = i
                break
    return text[start:end + 1]


# ═══════════════════════════════════════════════════════════════════════════
# Sub-auditors
# ═══════════════════════════════════════════════════════════════════════════

class DependencyAuditor:
    """Sub-audit A — parse manifests, flag outdated / vulnerable packages."""

    async def run(self, snapshot: RepoSnapshot) -> List[AuditFinding]:
        if not snapshot.manifests:
            return []
        manifests_text = "\n\n---\n\n".join(
            f"### {path}\n```\n{content[:3000]}\n```"
            for path, content in snapshot.manifests.items()
        )
        prompt = _DEPENDENCY_PROMPT.format(manifests=manifests_text)
        raw = await _call_llm(prompt, model="gemini-flash")
        self._last_raw = raw
        try:
            arr = json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            arr = []
        findings: List[AuditFinding] = []
        for item in arr:
            findings.append(AuditFinding(
                category=FindingCategory.DEPENDENCIES,
                severity=Severity(item.get("severity", "medium")),
                file_path=item.get("package_name", "unknown"),
                description=f"[{item.get('issue_type', 'unknown')}] {item.get('description', '')}",
                suggested_fix=item.get("suggested_fix"),
                fix_complexity=item.get("fix_complexity", 3),
                auto_fixable=item.get("issue_type") == "outdated" and item.get("fix_complexity", 3) <= 2,
            ))
        return findings


class CodeSmellDetector:
    """Sub-audit B — sample most-changed files, detect smells with Kimi K2."""

    async def run(self, snapshot: RepoSnapshot) -> List[AuditFinding]:
        # Identify top-20 most-changed files from commit history
        file_counts: Counter[str] = Counter()
        for commit in snapshot.recent_commits:
            for f in commit.files_changed:
                file_counts[f] += 1
        top_files = [f for f, _ in file_counts.most_common(20)]
        if not top_files:
            # fallback: grab a few source files from the tree
            exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb"}
            top_files = [
                p for p in snapshot.file_tree
                if any(p.endswith(e) for e in exts)
            ][:20]
        if not top_files:
            return []

        # We don't have actual file contents in the snapshot (FetchAgent doesn't
        # pull every file).  We simulate by building synthetic snippets from the
        # tree + commit messages to keep the demo self-contained.
        files_text = "\n\n---\n\n".join(
            f"### {path}\n(changed {file_counts.get(path, 0)} times in last 30 commits)"
            for path in top_files[:15]
        )
        prompt = _CODE_SMELL_PROMPT.format(files=files_text)
        raw = await _call_llm(prompt, model="kimi-k2")
        try:
            arr = json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            arr = []
        findings: List[AuditFinding] = []
        for item in arr:
            line_start = item.get("line_start", 0)
            line_end = item.get("line_end", line_start)
            findings.append(AuditFinding(
                category=FindingCategory.CODE_QUALITY,
                severity=Severity(item.get("severity", "medium")),
                file_path=item.get("file_path", "unknown"),
                line_range=(line_start, line_end) if line_start else None,
                description=f"[{item.get('issue_type', 'smell')}] {item.get('description', '')}",
                suggested_fix=item.get("suggested_fix"),
                fix_complexity=item.get("fix_complexity", 3),
                auto_fixable=item.get("auto_fixable", False),
            ))
        return findings


class TestCoverageAnalyzer:
    """Sub-audit C — structural coverage estimation."""

    async def run(self, snapshot: RepoSnapshot) -> List[AuditFinding]:
        tree = snapshot.file_tree
        test_files = [p for p in tree if "test" in p.lower() or "spec" in p.lower()]
        source_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb", ".php"}
        source_files = [p for p in tree if any(p.endswith(e) for e in source_exts)]
        non_test_source = [p for p in source_files if "test" not in p.lower() and "spec" not in p.lower()]
        if not non_test_source:
            return []

        sample_source = non_test_source[:30]
        sample_tests = test_files[:20]

        ft = "\n".join(tree[:200])  # cap for prompt size
        sf = "\n".join(sample_source[:20])
        tf = "\n".join(sample_tests[:20])

        prompt = _TEST_COVERAGE_PROMPT.format(file_tree=ft, source_files=sf, test_files=tf)
        raw = await _call_llm(prompt, model="gemini-flash")
        try:
            obj = json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            obj = {"estimated_coverage_percent": 0.0, "gaps": [], "recommendations": []}

        findings: List[AuditFinding] = []
        cov = obj.get("estimated_coverage_percent", 0.0)
        if cov < 30:
            sev = Severity.CRITICAL
        elif cov < 50:
            sev = Severity.HIGH
        elif cov < 70:
            sev = Severity.MEDIUM
        else:
            sev = Severity.LOW

        findings.append(AuditFinding(
            category=FindingCategory.TEST_COVERAGE,
            severity=sev,
            file_path="repository-wide",
            description=f"Estimated test coverage is {cov:.1f}% (structural heuristic). "
                        f"Recommended minimum is 70%.",
            suggested_fix="Add unit tests for uncovered modules. " + "; ".join(obj.get("recommendations", [])),
            fix_complexity=4,
            auto_fixable=False,
        ))

        for gap in obj.get("gaps", [])[:10]:
            if not gap.get("has_tests", True):
                findings.append(AuditFinding(
                    category=FindingCategory.TEST_COVERAGE,
                    severity=Severity.HIGH,
                    file_path=gap.get("module", "unknown"),
                    description=f"Module '{gap.get('module')}' appears to have no corresponding test file.",
                    suggested_fix=f"Create {gap.get('test_file_path') or 'tests for this module'}.",
                    fix_complexity=3,
                    auto_fixable=False,
                ))
        return findings


class SecurityScanner:
    """Sub-audit D — regex + LLM hybrid security scan."""

    # Patterns that are always scanned locally (fast, no LLM needed)
    _PATTERNS: List[tuple[str, str, Severity, str]] = [
        (r"\beval\s*\(", "Use of eval() detected", Severity.CRITICAL,
         "Replace eval() with safer parsing (e.g., json.loads, ast.literal_eval)."),
        (r"\bexec\s*\(", "Use of exec() detected", Severity.CRITICAL,
         "Remove exec() entirely; it allows arbitrary code execution."),
        (r"SELECT\s+.*\s+FROM\s+.*\+.*", "Possible SQL injection via string concatenation",
         Severity.CRITICAL, "Use parameterized queries / prepared statements."),
        (r"password\s*=\s*[\"'][^\"']+[\"']", "Hardcoded password", Severity.HIGH,
         "Move secrets to environment variables or a secrets manager."),
        (r"api[_-]?key\s*=\s*[\"'][^\"']+[\"']", "Hardcoded API key", Severity.HIGH,
         "Use environment variables or a secrets manager (e.g., AWS Secrets Manager)."),
        (r"secret\s*=\s*[\"'][^\"']+[\"']", "Hardcoded secret", Severity.HIGH,
         "Rotate the secret and load it from environment at runtime."),
        (r"TODO\s*:\s*.*(?:security|auth|crypt|encrypt|password|token)",
         "Security-related TODO found", Severity.MEDIUM,
         "Complete the security work described in the TODO before deploying."),
        (r"\.innerHTML\s*=", "Potential XSS via innerHTML assignment", Severity.HIGH,
         "Use textContent or a sanitization library like DOMPurify."),
        (r"pickle\.(loads|load)\s*\(", "Insecure deserialization with pickle", Severity.CRITICAL,
         "Replace pickle with json or use a safe serialization format."),
        (r"subprocess\.call\s*\([^)]*shell\s*=\s*True", "subprocess with shell=True", Severity.HIGH,
         "Pass command as a list and keep shell=False to avoid injection."),
        (r"os\.system\s*\(", "Use of os.system()", Severity.HIGH,
         "Replace with subprocess.run() using a list of arguments."),
        (r"requests\.get\s*\([^)]*verify\s*=\s*False", "SSL verification disabled", Severity.HIGH,
         "Never disable SSL verification in production. Remove verify=False."),
        (r"ALLOWED_HOSTS\s*=\s*\[\s*['\"]\*['\"]\s*\]", "Django ALLOWED_HOSTS set to wildcard",
         Severity.CRITICAL, "Set ALLOWED_HOSTS to your actual domain names."),
        (r"DEBUG\s*=\s*True", "DEBUG mode enabled (possible production config)", Severity.HIGH,
         "Set DEBUG=False in production and use environment-specific configs."),
    ]

    async def _pattern_scan(self, snapshot: RepoSnapshot) -> List[AuditFinding]:
        findings: List[AuditFinding] = []
        # Scan manifests + CI configs + README (not full source — we don't have it)
        all_texts: Dict[str, str] = {}
        all_texts.update(snapshot.manifests)
        all_texts.update(snapshot.ci_config)
        if snapshot.readme:
            all_texts["README"] = snapshot.readme

        for path, content in all_texts.items():
            for pat, desc, sev, fix in self._PATTERNS:
                for match in re.finditer(pat, content, re.IGNORECASE):
                    line_num = content[:match.start()].count("\n") + 1
                    findings.append(AuditFinding(
                        category=FindingCategory.SECURITY,
                        severity=sev,
                        file_path=path,
                        line_range=(line_num, line_num),
                        description=desc,
                        suggested_fix=fix,
                        fix_complexity=2 if "env" in fix else 3,
                        auto_fixable="env" in fix.lower() or "environment" in fix.lower(),
                    ))
        return findings

    async def _llm_scan(self, snapshot: RepoSnapshot) -> List[AuditFinding]:
        # Build synthetic snippets from file tree + commit messages
        snippets = []
        for path in snapshot.file_tree[:50]:
            if any(path.endswith(e) for e in [".py", ".js", ".ts", ".go", ".rs", ".java"]):
                snippets.append(f"### {path}\n// code not available in snapshot; review manually")
        if not snippets:
            return []
        prompt = _SECURITY_PROMPT.format(snippets="\n\n---\n\n".join(snippets[:30]))
        raw = await _call_llm(prompt, model="gemini-flash")
        try:
            arr = json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            arr = []
        findings: List[AuditFinding] = []
        for item in arr:
            line_start = item.get("line_start", 0)
            line_end = item.get("line_end", line_start)
            findings.append(AuditFinding(
                category=FindingCategory.SECURITY,
                severity=Severity(item.get("severity", "medium")),
                file_path=item.get("file_path", "unknown"),
                line_range=(line_start, line_end) if line_start else None,
                description=f"[{item.get('issue_type', 'security')}] {item.get('description', '')}",
                suggested_fix=item.get("suggested_fix"),
                fix_complexity=item.get("fix_complexity", 3),
                auto_fixable=item.get("auto_fixable", False),
            ))
        return findings

    async def run(self, snapshot: RepoSnapshot) -> List[AuditFinding]:
        pattern_findings, llm_findings = await asyncio.gather(
            self._pattern_scan(snapshot),
            self._llm_scan(snapshot),
        )
        # deduplicate by (file_path, description)
        seen: Set[str] = set()
        merged: List[AuditFinding] = []
        for f in pattern_findings + llm_findings:
            key = f"{f.file_path}:{f.description[:80]}"
            if key not in seen:
                seen.add(key)
                merged.append(f)
        return merged


# ═══════════════════════════════════════════════════════════════════════════
# Main AuditAgent
# ═══════════════════════════════════════════════════════════════════════════

class AuditAgent(BaseAgent):
    """
    Agent 2 — AuditAgent.

    Orchestrates four parallel sub-audits and merges their findings.
    """

    name = "AuditAgent"

    async def run(self, context: AgentContext) -> AgentResult:
        if context.snapshot is None:
            return AgentResult(success=False, error="No repo snapshot available.")

        snap = context.snapshot
        self._emit(context, AgentStatus.RUNNING,
                   "Launching 4 parallel sub-audits …")

        dep_auditor = DependencyAuditor()
        smell_detector = CodeSmellDetector()
        coverage_analyzer = TestCoverageAnalyzer()
        security_scanner = SecurityScanner()

        dep_f, smell_f, cov_f, sec_f = await asyncio.gather(
            dep_auditor.run(snap),
            smell_detector.run(snap),
            coverage_analyzer.run(snap),
            security_scanner.run(snap),
            return_exceptions=True,
        )

        all_findings: List[AuditFinding] = []
        for label, findings in [("dependencies", dep_f), ("code_quality", smell_f),
                                ("test_coverage", cov_f), ("security", sec_f)]:
            if isinstance(findings, Exception):
                self._emit(context, AgentStatus.ERROR,
                           f"Sub-audit {label} raised {findings}")
                continue
            all_findings.extend(findings)
            self._emit(context, AgentStatus.RUNNING,
                       f"Sub-audit {label}: {len(findings)} findings")

        # attach to context
        context.findings = all_findings

        # count by category for the event
        counts: Dict[str, int] = {}
        for f in all_findings:
            counts[f.category.value] = counts.get(f.category.value, 0) + 1

        self._emit(context, AgentStatus.DONE,
                   f"Audit complete — {len(all_findings)} total findings",
                   data={"total": len(all_findings), "by_category": counts})

        return AgentResult(
            success=True,
            data={"findings": [f.model_dump() for f in all_findings]},
        )
