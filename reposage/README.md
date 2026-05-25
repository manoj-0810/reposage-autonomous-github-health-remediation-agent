# RepoSage — Autonomous GitHub Health Agent

**RepoSage** is a production-ready multi-agent system that performs deep health
audits on any public GitHub repository. It detects security vulnerabilities,
outdated dependencies, code smells, and test coverage gaps — then automatically
opens prioritized GitHub Issues and draft Pull Requests with fixes.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Agent Descriptions](#agent-descriptions)
3. [Tech Stack](#tech-stack)
4. [Quick Start](#quick-start)
5. [5-Minute Demo Walkthrough](#5-minute-demo-walkthrough)
6. [API Reference](#api-reference)
7. [Frontend Pages](#frontend-pages)
8. [Project Structure](#project-structure)
9. [Environment Variables](#environment-variables)
10. [Running Tests](#running-tests)

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────┐
                    │           Next.js 14 Frontend            │
                    │  ┌─────────┐ ┌──────────┐ ┌──────────┐ │
                    │  │  Home   │ │  Scan    │ │  Repo    │ │
                    │  │  Page   │ │  Live    │ │  Dashboard│ │
                    │  │  (/)    │ │  (/scan) │ │  (/repo) │ │
                    │  └────┬────┘ └────┬─────┘ └────┬─────┘ │
                    │       │            │            │        │
                    │       └────────────┼────────────┘        │
                    │                    │ SSE (EventSource)    │
                    └────────────────────┼─────────────────────┘
                                         │
                    ┌────────────────────┼─────────────────────┐
                    │       FastAPI Backend (Python 3.11)      │
                    │                    │                      │
                    │  ┌─────────────────┴─────────────────┐   │
                    │  │      OrchestratorAgent (Agent 6)    │   │
                    │  │  Manages pipeline + error recovery  │   │
                    │  │  Computes final HealthScore (0-100) │   │
                    │  └─────────────────┬─────────────────┘   │
                    │                    │                       │
                    │  ┌─────────────────┼─────────────────┐    │
                    │  │                 │                 │    │
                    │  ▼                 ▼                 ▼    │
                    │ FetchAgent    AuditAgent    Prioritizer   │
                    │ (Agent 1)     (Agent 2)     (Agent 3)     │
                    │   │              │                          │
                    │   │    ┌─────────┼─────────┐               │
                    │   │    │         │         │               │
                    │   │    ▼         ▼         ▼               │
                    │   │  DepAuditor CodeSmell  TestCovAnalyzer  │
                    │   │  (Gemini)   (Kimi K2)  (Gemini)        │
                    │   │  SecurityScanner                       │
                    │   │  (regex + Gemini)                      │
                    │   │              │                          │
                    │   │              ▼                          │
                    │   │         FixAgent (Agent 4)              │
                    │   │         Generates unified-diff patches  │
                    │   │              │                          │
                    │   │              ▼                          │
                    │   │         ActionAgent (Agent 5)           │
                    │   │         Creates GitHub Issues & PRs     │
                    │   │                                         │
                    │  ┌┴─────────────────────────────────────┐  │
                    │  │   PostgreSQL        Redis (job queue)  │  │
                    │  │   (scan history)    (event queues)     │  │
                    │  └──────────────────────────────────────┘  │
                    └─────────────────────────────────────────────┘

  GitHub REST API ◄──────────────────────────────────────────────────►
    (GitAgent semantics)

  LLM APIs:
    • Kimi K2 API  → Orchestrator, Prioritizer, FixAgent, CodeSmellDetector
    • Gemini 2.5 Flash API → DependencyAuditor, TestCoverageAnalyzer, SecurityScanner
```

**Pipeline Flow:**

```
POST /api/scans  →  UUID returned
                          │
                          ▼
                   [OrchestratorAgent]
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    [FetchAgent]    [AuditAgent]    [PrioritizerAgent]
          │          (4 parallel      │
          │           sub-audits)     ▼
          │               │      [HealthScore]
          ▼               ▼           │
    RepoSnapshot    List[Finding]     │
                          │           │
                          ▼           │
                    [FixAgent]        │
                 List[CodePatch]      │
                          │           │
                          ▼           │
                    [ActionAgent] ◄───┘
                 Issues + Draft PRs
                          │
                          ▼
                   SSE stream closed
                   Scan persisted to PostgreSQL
```

---

## Agent Descriptions

### Agent 1 — FetchAgent
**Role:** Retrieves the complete repository snapshot from GitHub.

**What it does:**
- Queries the GitHub REST API for the repository's file tree, default branch,
  star/fork counts, and primary language.
- Fetches all dependency manifests (`package.json`, `requirements.txt`,
  `go.mod`, `Cargo.toml`, `pom.xml`, etc.).
- Retrieves the latest 30 commits with file-change metadata.
- Fetches open pull requests.
- Downloads README and CI configuration files (`.github/workflows`,
  `.gitlab-ci.yml`, etc.).

**Output:** `RepoSnapshot` dataclass with all of the above.

---

### Agent 2 — AuditAgent
**Role:** Runs four parallel sub-audits to detect problems.

**Sub-audits (all launched via `asyncio.gather`):**

| Sub-agent | LLM Backend | What it finds |
|-----------|-------------|---------------|
| `DependencyAuditor` | Gemini 2.5 Flash | Outdated packages, known vulnerabilities, deprecated deps, version conflicts |
| `CodeSmellDetector` | Kimi K2 | Dead code, god classes/functions, missing error handling, hardcoded secrets, TODO bombs |
| `TestCoverageAnalyzer` | Gemini 2.5 Flash | Structural gaps between source files and test files, estimated coverage % |
| `SecurityScanner` | Gemini 2.5 Flash + regex | `eval()`, `exec()`, SQL injection, unvalidated inputs, exposed credentials, weak crypto |

**Output:** Merged `List[AuditFinding]` with severity, file path, line range,
description, suggested fix, and fix complexity.

---

### Agent 3 — PrioritizerAgent
**Role:** Ranks findings and computes the Health Score.

**What it does:**
- Uses Kimi K2 to estimate **blast radius** (1–5) for each finding.
- Computes **priority score** = `severity_weight × blast_radius / fix_complexity`.
- Returns the **top 10 findings** sorted by priority.
- Groups related findings into **themes** (e.g., "3 security issues in auth/").
- Calculates per-dimension health scores (security, dependencies, code quality,
  test coverage) and the weighted overall score.

**Score Weights:** Security 40%, Dependencies 25%, Code Quality 20%,
Test Coverage 15%.

**Output:** `PrioritizedResult` with top findings, themes, and score breakdown.

---

### Agent 4 — FixAgent
**Role:** Generates syntactically-valid code patches for auto-fixable findings.

**What it does:**
- Iterates over findings marked `auto_fixable=True` with `fix_complexity ≤ 3`.
- Uses Kimi K2 to generate a **unified diff** patch for each.
- Validates every patch has `---`, `+++`, and `@@` headers.
- Returns only validated patches.

**Output:** `List[CodePatch]` with target file, patch text, description, and
finding index.

---

### Agent 5 — ActionAgent
**Role:** Creates GitHub Issues and opens draft PRs.

**What it does:**
- Creates a **GitHub Issue** for each top-priority finding with:
  - Descriptive title with severity badge
  - Category and severity labels (`reposage`, `security`, `tech-debt`, etc.)
  - File links with line numbers
  - Suggested fix explanation
- For each validated patch:
  - Creates a new branch (`reposage/fix-{n}`)
  - Commits the patch
  - Opens a **draft PR** linked to the corresponding Issue
- Posts a **RepoSage Health Report** summary Issue with the overall score and
  links to all created items.

**Output:** `ActionResult` with lists of created Issues and PRs.

---

### Agent 6 — OrchestratorAgent
**Role:** Manages the entire pipeline end-to-end.

**What it does:**
- Sequentially runs: Fetch → Audit → Prioritize → Fix → Action.
- Streams real-time `AgentEvent` objects via callback (wired to SSE).
- **Graceful error handling:** if one sub-agent fails, logs the error and
  continues with the remaining pipeline.
- Persists the final scan result (health score, findings, patches, actions) to
  PostgreSQL.

**Output:** Final `AgentResult` with pipeline timing and summary stats.

---

## Tech Stack

### Backend
| Component | Technology |
|-----------|------------|
| Framework | FastAPI (Python 3.11+) |
| Async HTTP | `httpx` |
| Database | PostgreSQL 16 + `asyncpg` |
| Job Queue | Redis 7 (for `rq` / Celery) |
| Deep Analysis LLM | Kimi K2 API |
| Fast Triage LLM | Gemini 2.5 Flash API |
| GitHub API | REST API v3 (GitAgent semantics) |
| Testing | `pytest` + `pytest-asyncio` |

### Frontend
| Component | Technology |
|-----------|------------|
| Framework | Next.js 14 (App Router) |
| Styling | Tailwind CSS |
| Components | shadcn/ui (Radix + CVA) |
| Charts | Recharts |
| Real-time | SSE (`EventSource`) |
| Icons | Lucide React |

### Infrastructure
| Component | Technology |
|-----------|------------|
| Orchestration | Docker Compose |
| Services | FastAPI, Next.js, PostgreSQL, Redis |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- GitHub account (for PAT to create Issues/PRs)
- Kimi K2 API key ([Moonshot AI](https://platform.moonshot.cn/))
- Gemini 2.5 Flash API key ([Google AI Studio](https://aistudio.google.com/))

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/reposage.git
cd reposage
cp .env.example .env
# Edit .env with your API keys:
#   KIMI_API_KEY=your-kimi-key
#   GEMINI_API_KEY=your-gemini-key
```

### 2. Start Everything

```bash
docker-compose up --build
```

This starts four containers:
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **FastAPI backend** on `http://localhost:8000`
- **Next.js frontend** on `http://localhost:3000`

### 3. Verify

```bash
# Health check
curl http://localhost:8000/health
# → {"status": "ok", "service": "reposage-api"}

# OpenAPI docs
open http://localhost:8000/docs

# Frontend
open http://localhost:3000
```

---

## 5-Minute Demo Walkthrough

### Step 1 — Start a Scan
1. Open `http://localhost:3000`
2. Paste any public GitHub repo URL, e.g.:
   ```
   https://github.com/facebook/react
   ```
3. Optionally paste a **GitHub Personal Access Token** (with `repo` scope) if
   you want RepoSage to create real Issues and PRs.
4. Click **"Run Scan"**.

### Step 2 — Watch the Live Feed
- You're redirected to `/scan/{uuid}`
- The **Agent Pipeline** panel shows 5 steps: Fetch → Audit → Prioritize → Fix → Action
- Each step animates from `pending → running → done`
- The **Live Agent Log** streams real-time messages via SSE
- Findings appear as color-coded cards (red=critical, orange=high, yellow=medium, green=low)

### Step 3 — View Results
- When the pipeline completes, the **Health Score** meter animates to the final score
- Four dimension bars show Security, Dependencies, Code Quality, and Test Coverage
- Created GitHub Issues and draft PRs appear with links
- A **"View Full Health Report on GitHub"** button links to the summary Issue

### Step 4 — Check the Dashboard
- Navigate to `/repo/{owner}/{repo}` (e.g., `/repo/facebook/react`)
- See a **line chart** of health scores over time
- A **donut chart** breaks down the latest scan by dimension
- A **table** lists all historical scans with per-dimension scores

---

## API Reference

### `POST /api/scans`
Kick off a new scan.

**Body:**
```json
{
  "repo_url": "https://github.com/owner/repo",
  "github_token": "ghp_xxxxxxxxxxxx"
}
```

**Response:**
```json
{
  "scan_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued"
}
```

### `GET /api/scans/{scan_id}`
Get full scan result.

**Response:**
```json
{
  "scan_id": "...",
  "repo_url": "...",
  "owner": "owner",
  "repo": "repo",
  "status": "completed",
  "health_score": {
    "overall": 72.5,
    "security": 60,
    "dependencies": 85,
    "code_quality": 78,
    "test_coverage": 55
  },
  "findings": [...],
  "patches": [...],
  "actions": {
    "issues": [{"title": "...", "url": "...", "number": 1}],
    "pull_requests": [{"title": "...", "url": "...", "number": 1}],
    "summary_issue_url": "https://github.com/owner/repo/issues/99"
  }
}
```

### `GET /api/scans/{scan_id}/stream`
SSE endpoint. Streams `AgentEvent` JSON lines:

```json
data: {"agent":"FetchAgent","status":"running","message":"Fetching repository data...","timestamp":"2024-01-15T10:00:00Z"}
```

### `GET /api/repos/{owner}/{repo}/history`
Get past health scores for the repo dashboard sparkline.

**Response:**
```json
[
  {
    "scan_id": "...",
    "scanned_at": "2024-01-15T10:00:00Z",
    "health_score": 72.5,
    "security": 60,
    "dependencies": 85,
    "code_quality": 78,
    "test_coverage": 55
  }
]
```

---

## Frontend Pages

| Page | Route | Purpose |
|------|-------|---------|
| Home | `/` | Hero section, repo URL input form, feature cards, sample repos |
| Scan Live | `/scan/[id]` | Real-time agent pipeline steps, SSE log stream, findings cards, health score meter, created Issues/PRs |
| Repo Dashboard | `/repo/[owner]/[repo]` | Health score line chart (Recharts), dimension donut chart, scan history table |

---

## Project Structure

```
reposage/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                  # FastAPI entrypoint
│   ├── agents/
│   │   ├── base.py              # BaseAgent interface + SSE event bus
│   │   ├── fetch_agent.py       # Agent 1 — repo snapshot
│   │   ├── audit_agent.py       # Agent 2 — 4 parallel sub-audits
│   │   ├── prioritizer_agent.py # Agent 3 — scoring + themes
│   │   ├── fix_agent.py         # Agent 4 — unified-diff patches
│   │   ├── action_agent.py      # Agent 5 — GitHub Issues & PRs
│   │   └── orchestrator.py      # Agent 6 — pipeline orchestrator
│   ├── models/
│   │   └── schemas.py           # All Pydantic dataclasses
│   ├── api/
│   │   └── routes.py            # FastAPI endpoints (HTTP + SSE)
│   ├── db/
│   │   └── database.py          # asyncpg persistence layer
│   └── tests/
│       └── test_agents.py       # pytest suite (1 test per agent)
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── app/
│   │   ├── layout.tsx           # Root layout with Inter font
│   │   ├── page.tsx             # Home page (hero + scan form)
│   │   ├── scan/[id]/
│   │   │   └── page.tsx         # Live scan view (SSE + findings)
│   │   └── repo/[owner]/[repo]/
│   │       └── page.tsx         # Repo dashboard (Recharts)
│   ├── components/
│   │   ├── AgentFeed.tsx        # Real-time agent step + log UI
│   │   ├── FindingCard.tsx      # Color-coded finding card
│   │   └── HealthMeter.tsx      # Animated SVG score ring
│   └── lib/
│       └── utils.ts             # cn() helper + severity colors
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KIMI_API_KEY` | **Yes** | Kimi K2 API key for deep analysis agents |
| `GEMINI_API_KEY` | **Yes** | Gemini 2.5 Flash API key for fast triage |
| `DATABASE_URL` | No | PostgreSQL DSN (default: `postgresql://reposage:reposage@localhost:5432/reposage`) |
| `REDIS_URL` | No | Redis connection string (default: `redis://localhost:6379/0`) |
| `PORT` | No | FastAPI port (default: `8000`) |

---

## Running Tests

```bash
# Backend tests (run inside the backend container)
docker-compose exec backend pytest tests/ -v

# Or locally with venv
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/test_agents.py -v
```

**Test coverage:** Each agent has at least one happy-path test with mocked
GitHub API / LLM responses. Tests verify:
- `FetchAgent` builds a valid `RepoSnapshot`
- `AuditAgent` runs 4 sub-audits and merges findings
- `PrioritizerAgent` ranks findings and computes themes
- `FixAgent` generates validated patches
- `ActionAgent` creates Issues via mocked GitHub API
- `OrchestratorAgent` runs the full pipeline and computes health score
