"""
RepoSage — FetchAgent.
Retrieves a complete repository snapshot via the GitHub REST API:
file tree, dependency manifests, recent commits, open PRs, README, and CI configs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from agents.base import BaseAgent
from models.schemas import (
    AgentContext,
    AgentResult,
    AgentStatus,
    CommitInfo,
    PullRequestInfo,
    RepoSnapshot,
)

# Manifest files that the agent looks for.
_MANIFEST_PATTERNS = [
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "Gemfile",
    "Gemfile.lock",
    "pom.xml",
    "build.gradle",
    "gradle.properties",
    "composer.json",
    "composer.lock",
    "mix.exs",
    "rebar.config",
    "project.clj",
    "build.sbt",
    "Package.swift",
    "Podfile",
    "Dockerfile",
    "docker-compose.yml",
    "poetry.lock",
    "uv.lock",
]

_CI_PATTERNS = [
    ".github/workflows",
    ".circleci",
    ".travis.yml",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
    "cloudbuild.yaml",
    ".drone.yml",
    "appveyor.yml",
    "codecov.yml",
    ".coveragerc",
]

_README_PATTERNS = [
    "README.md",
    "README.rst",
    "README.txt",
    "README",
]

_KEY_FILES = [
    ".gitignore",
    "Makefile",
    "justfile",
    "LICENSE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CHANGELOG.md",
]


class FetchAgent(BaseAgent):
    """
    Agent 1 — FetchAgent.

    Uses the GitHub REST API to build a structured RepoSnapshot
    that downstream agents consume.
    """

    name = "FetchAgent"

    def __init__(self, max_file_size: int = 500_000) -> None:
        super().__init__()
        self._max_file_size = max_file_size

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────

    def _github_api(self, token: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
        }

        # Add auth header only if token exists
        if token and token.strip():
            headers["Authorization"] = f"token {token.strip()}"

        return headers

    async def _get(self, url: str, headers: Dict[str, str]) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _fetch_default_branch(
        self,
        owner: str,
        repo: str,
        headers: Dict[str, str],
    ) -> str:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        data = await self._get(url, headers)
        return data.get("default_branch", "main")

    async def _fetch_repo_meta(
        self,
        owner: str,
        repo: str,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        return await self._get(url, headers)

    async def _fetch_tree(
        self,
        owner: str,
        repo: str,
        headers: Dict[str, str],
        branch: str = "main",
    ) -> List[str]:

        url = (
            f"https://api.github.com/repos/{owner}/{repo}/"
            f"git/trees/{branch}?recursive=1"
        )

        data = await self._get(url, headers)
        tree = data.get("tree", [])

        return [
            item["path"]
            for item in tree
            if item.get("type") == "blob"
        ]

    async def _fetch_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        headers: Dict[str, str],
    ) -> Optional[str]:

        url = (
            f"https://api.github.com/repos/{owner}/{repo}/"
            f"contents/{path}?ref=main"
        )

        try:
            data = await self._get(url, headers)

            import base64

            if isinstance(data, dict) and data.get("encoding") == "base64":
                return base64.b64decode(
                    data["content"]
                ).decode("utf-8", errors="replace")

            return None

        except Exception:
            return None

    async def _fetch_commits(
        self,
        owner: str,
        repo: str,
        headers: Dict[str, str],
        limit: int = 30,
    ) -> List[CommitInfo]:

        url = (
            f"https://api.github.com/repos/{owner}/{repo}/"
            f"commits?per_page={limit}"
        )

        commits = await self._get(url, headers)

        result: List[CommitInfo] = []

        for c in commits:
            commit_data = c.get("commit", {})
            author_info = commit_data.get("author", {})

            result.append(
                CommitInfo(
                    sha=c.get("sha", ""),
                    message=commit_data.get("message", ""),
                    author=author_info.get("name", "unknown"),
                    date=datetime.fromisoformat(
                        author_info.get(
                            "date",
                            "2024-01-01T00:00:00Z"
                        ).replace("Z", "+00:00")
                    ),
                    files_changed=[],
                )
            )

        return result

    async def _fetch_prs(
        self,
        owner: str,
        repo: str,
        headers: Dict[str, str],
    ) -> List[PullRequestInfo]:

        url = (
            f"https://api.github.com/repos/{owner}/{repo}/"
            f"pulls?state=open&per_page=30"
        )

        prs = await self._get(url, headers)

        return [
            PullRequestInfo(
                number=p.get("number", 0),
                title=p.get("title", ""),
                author=p.get("user", {}).get("login", "unknown"),
                state=p.get("state", "open"),
                created_at=datetime.fromisoformat(
                    p.get(
                        "created_at",
                        "2024-01-01T00:00:00Z"
                    ).replace("Z", "+00:00")
                ),
                updated_at=datetime.fromisoformat(
                    p.get(
                        "updated_at",
                        "2024-01-01T00:00:00Z"
                    ).replace("Z", "+00:00")
                ),
            )
            for p in prs
        ]

    # ──────────────────────────────────────────────────────────────
    # Main
    # ──────────────────────────────────────────────────────────────

    async def run(self, context: AgentContext) -> AgentResult:

        ctx = context

        self._emit(
            ctx,
            AgentStatus.RUNNING,
            f"Fetching repository data for {ctx.owner}/{ctx.repo} …"
        )

        headers = self._github_api(ctx.github_token)

        # Default branch
        try:
            branch = await self._fetch_default_branch(
                ctx.owner,
                ctx.repo,
                headers,
            )
        except Exception:
            branch = "main"

        meta = await self._fetch_repo_meta(
            ctx.owner,
            ctx.repo,
            headers,
        )

        language = meta.get("language")
        stars = meta.get("stargazers_count", 0)
        forks = meta.get("forks_count", 0)

        self._emit(
            ctx,
            AgentStatus.RUNNING,
            f"Resolved default branch: {branch}"
        )

        # File tree
        tree = await self._fetch_tree(
            ctx.owner,
            ctx.repo,
            headers,
            branch,
        )

        self._emit(
            ctx,
            AgentStatus.RUNNING,
            f"Discovered {len(tree)} files in tree"
        )

        # Special files
        manifest_paths = [
            p for p in tree
            if any(p.endswith(m) for m in _MANIFEST_PATTERNS)
        ]

        ci_paths = [
            p for p in tree
            if any(p.startswith(c) for c in _CI_PATTERNS)
        ]

        readme_path = next(
            (
                p for p in tree
                if any(
                    p.rsplit("/", 1)[-1].lower() == r.lower()
                    for r in _README_PATTERNS
                )
            ),
            None,
        )

        async def _fetch_named(paths: List[str]) -> Dict[str, str]:
            if not paths:
                return {}
            async def _fetch_one(p: str):
                try:
                    content = await self._fetch_file_content(
                        ctx.owner,
                        ctx.repo,
                        p,
                        headers,
                    )
                    return p, content
                except Exception:
                    return p, None
            results = await asyncio.gather(*[_fetch_one(p) for p in paths])
            return {p: c for p, c in results if c is not None}

        # Select up to 10 key source files to fetch content for
        source_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cs", ".rb", ".ipynb"}
        ignore_keywords = {"test", "spec", "node_modules", "vendor", "dist", "build", "CI", ".github", ".git"}
        
        source_files = [
            p for p in tree
            if any(p.endswith(ext) for ext in source_exts)
            and not any(k in p.lower() for k in ignore_keywords)
        ][:10]

        from models.schemas import RepoFile
        source_contents = await _fetch_named(source_files)
        files_dict = {}
        for p, content in source_contents.items():
            if p.endswith(".ipynb"):
                import json
                try:
                    nb = json.loads(content)
                    cells = nb.get("cells", [])
                    extracted = []
                    for idx, cell in enumerate(cells):
                        if cell.get("cell_type") == "code":
                            source = cell.get("source", [])
                            if isinstance(source, list):
                                extracted.append(f"# --- Cell {idx} ---")
                                extracted.extend(source)
                                extracted.append("\n")
                            elif isinstance(source, str):
                                extracted.append(f"# --- Cell {idx} ---")
                                extracted.append(source)
                                extracted.append("\n")
                    content = "".join(extracted)
                except Exception:
                    pass

            files_dict[p] = RepoFile(
                path=p,
                size=len(content),
                content=content,
                is_binary=False
            )

        manifests, readme, ci_configs = await asyncio.gather(
            _fetch_named(manifest_paths),

            self._fetch_file_content(
                ctx.owner,
                ctx.repo,
                readme_path,
                headers,
            ) if readme_path else asyncio.sleep(0),

            _fetch_named(ci_paths),
        )

        commits, prs = await asyncio.gather(
            self._fetch_commits(
                ctx.owner,
                ctx.repo,
                headers,
            ),

            self._fetch_prs(
                ctx.owner,
                ctx.repo,
                headers,
            ),
        )

        snapshot = RepoSnapshot(
            owner=ctx.owner,
            repo=ctx.repo,
            default_branch=branch,
            file_tree=tree,
            files=files_dict,
            manifests=manifests,
            recent_commits=commits,
            open_prs=prs,
            readme=readme if isinstance(readme, str) else None,
            ci_config=ci_configs,
            language=language,
            stars=stars,
            forks=forks,
        )

        ctx.snapshot = snapshot

        self._emit(
            ctx,
            AgentStatus.DONE,
            f"Fetch complete — {len(tree)} files"
        )

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "snapshot": snapshot.model_dump()
            },
        )