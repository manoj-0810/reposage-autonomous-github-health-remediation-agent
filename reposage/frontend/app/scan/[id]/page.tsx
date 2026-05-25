"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock,
  ExternalLink,
  GitPullRequest,
  Github,
  Loader2,
  Play,
  XCircle,
} from "lucide-react";
import { getSeverityColor, getSeverityDot } from "@/lib/utils";
import HealthMeter from "@/components/HealthMeter";

interface AgentEvent {
  agent: string;
  status: "pending" | "running" | "done" | "error";
  message: string;
  timestamp: string;
  data?: Record<string, any>;
}

interface Finding {
  category: string;
  severity: string;
  file_path: string;
  line_range: [number, number] | null;
  description: string;
  suggested_fix?: string;
}

interface ScanData {
  scan_id: string;
  repo_url: string;
  owner: string;
  repo: string;
  status: string;
  health_score: {
    overall: number;
    security: number;
    dependencies: number;
    code_quality: number;
    test_coverage: number;
  } | null;
  findings: Finding[];
  actions: {
    issues: { title: string; url: string; number: number; labels: string[] }[];
    pull_requests: { title: string; url: string; number: number }[];
    summary_issue_url?: string;
  };
}

const AGENT_STEPS = [
  { key: "FetchAgent", label: "Fetch Repository" },
  { key: "AuditAgent", label: "Run Audits" },
  { key: "PrioritizerAgent", label: "Prioritize Findings" },
  { key: "FixAgent", label: "Generate Patches" },
  { key: "ActionAgent", label: "Open Issues & PRs" },
];

export default function ScanLivePage() {
  const { id } = useParams() as { id: string };
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [scanData, setScanData] = useState<ScanData | null>(null);
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // SSE connection
  useEffect(() => {
    const evtSource = new EventSource(`/api/scans/${id}/stream`);
    setConnected(true);

    evtSource.onmessage = (e) => {
      const payload = JSON.parse(e.data);
      if (payload.done) {
        setDone(true);
        evtSource.close();
        return;
      }
      setEvents((prev) => [...prev, payload]);
    };

    evtSource.onerror = () => {
      setConnected(false);
      evtSource.close();
    };

    return () => evtSource.close();
  }, [id]);

  // Poll for final scan data
  useEffect(() => {
    if (!done) return;
    fetch(`/api/scans/${id}`)
      .then((r) => r.json())
      .then((d) => setScanData(d))
      .catch(() => {});
  }, [done, id]);

  // Auto-scroll events
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const agentStatus = (agentKey: string) => {
    const ev = events
      .filter((e) => e.agent === agentKey)
      .pop();
    if (!ev) return "pending";
    return ev.status;
  };

  const findings = scanData?.findings || [];
  const health = scanData?.health_score;

  return (
    <main className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Link>
            <span className="text-slate-300">|</span>
            <Github className="h-5 w-5 text-slate-700" />
            <span className="text-sm font-semibold text-slate-800">
              {scanData ? `${scanData.owner}/${scanData.repo}` : "Scanning…"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {connected ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 ring-1 ring-green-200">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                Live
              </span>
            ) : done ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
                <CheckCircle2 className="h-3 w-3" />
                Complete
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
                <Clock className="h-3 w-3" />
                Reconnecting…
              </span>
            )}
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="grid gap-6 lg:grid-cols-12">
          {/* Left Panel — Agent Steps + Event Feed */}
          <div className="lg:col-span-5 space-y-4">
            {/* Agent Steps */}
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-500">
                Agent Pipeline
              </h2>
              <div className="space-y-3">
                {AGENT_STEPS.map((step, i) => {
                  const status = agentStatus(step.key);
                  return (
                    <div
                      key={step.key}
                      className="flex items-center gap-3 rounded-lg p-2.5 transition"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-600">
                        {status === "done" ? (
                          <CheckCircle2 className="h-5 w-5 text-green-600" />
                        ) : status === "running" ? (
                          <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                        ) : status === "error" ? (
                          <XCircle className="h-5 w-5 text-red-500" />
                        ) : (
                          i + 1
                        )}
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-800">
                          {step.label}
                        </p>
                        <p className="text-xs text-slate-500">
                          {status === "pending"
                            ? "Waiting…"
                            : status === "running"
                            ? "Processing…"
                            : status === "done"
                            ? "Complete"
                            : "Failed"}
                        </p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-slate-300" />
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Live Event Feed */}
            <div className="rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
              <div className="border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Live Agent Log
                </h2>
              </div>
              <div className="h-96 overflow-y-auto custom-scrollbar px-5 py-3">
                <div className="space-y-2">
                  {events.length === 0 && (
                    <p className="text-center text-sm text-slate-400 py-12">
                      Waiting for agents to start…
                    </p>
                  )}
                  {events.map((ev, i) => (
                    <div
                      key={i}
                      className="animate-slide-in rounded-lg bg-slate-50 px-3 py-2 text-xs"
                    >
                      <div className="mb-0.5 flex items-center gap-1.5">
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            ev.status === "done"
                              ? "bg-green-500"
                              : ev.status === "error"
                              ? "bg-red-500"
                              : ev.status === "running"
                              ? "bg-blue-500 animate-pulse"
                              : "bg-slate-300"
                          }`}
                        />
                        <span className="font-semibold text-slate-700">
                          {ev.agent}
                        </span>
                        <span className="text-slate-400">
                          {new Date(ev.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      <p className="pl-3 text-slate-600">{ev.message}</p>
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>
              </div>
            </div>
          </div>

          {/* Right Panel — Findings */}
          <div className="lg:col-span-7 space-y-4">
            {/* Health Score */}
            {health && (
              <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
                <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
                  <div>
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                      Health Score
                    </h2>
                    <p className="mt-1 text-3xl font-extrabold text-slate-900">
                      {health.overall}
                      <span className="text-lg font-medium text-slate-400">
                        /100
                      </span>
                    </p>
                  </div>
                  <HealthMeter score={health.overall} size={120} />
                </div>
                <div className="mt-4 grid grid-cols-4 gap-3">
                  {[
                    { label: "Security", value: health.security, color: "bg-red-500" },
                    { label: "Dependencies", value: health.dependencies, color: "bg-blue-500" },
                    { label: "Code Quality", value: health.code_quality, color: "bg-purple-500" },
                    { label: "Test Coverage", value: health.test_coverage, color: "bg-emerald-500" },
                  ].map((dim) => (
                    <div key={dim.label} className="text-center">
                      <div className="mb-1 text-xs font-medium text-slate-500">
                        {dim.label}
                      </div>
                      <div className="h-2 w-full rounded-full bg-slate-100">
                        <div
                          className={`h-2 rounded-full ${dim.color} transition-all`}
                          style={{ width: `${dim.value}%` }}
                        />
                      </div>
                      <div className="mt-0.5 text-xs font-bold text-slate-700">
                        {dim.value}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Findings */}
            <div className="rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
              <div className="border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Findings
                  {findings.length > 0 && (
                    <span className="ml-2 inline-flex h-5 items-center rounded-full bg-slate-100 px-2 text-xs text-slate-600">
                      {findings.length}
                    </span>
                  )}
                </h2>
              </div>
              <div className="max-h-[600px] overflow-y-auto custom-scrollbar">
                {findings.length === 0 && (
                  <p className="px-5 py-12 text-center text-sm text-slate-400">
                    {done
                      ? "No findings detected. Great job!"
                      : "Findings will appear as audits complete…"}
                  </p>
                )}
                <div className="divide-y divide-slate-100">
                  {findings.map((f, i) => (
                    <div key={i} className="px-5 py-4">
                      <div className="mb-2 flex items-center gap-2">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold ${getSeverityColor(
                            f.severity
                          )}`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${getSeverityDot(
                              f.severity
                            )}`}
                          />
                          {f.severity}
                        </span>
                        <span className="text-xs font-medium text-slate-500">
                          {f.category}
                        </span>
                      </div>
                      <p className="mb-1 text-sm font-medium text-slate-800">
                        {f.file_path}
                        {f.line_range && (
                          <span className="ml-1 font-normal text-slate-400">
                            :{f.line_range[0]}-{f.line_range[1]}
                          </span>
                        )}
                      </p>
                      <p className="text-sm text-slate-600">
                        {f.description}
                      </p>
                      {f.suggested_fix && (
                        <p className="mt-1.5 rounded-md bg-blue-50 px-3 py-1.5 text-xs text-blue-700">
                          <span className="font-semibold">Fix:</span>{" "}
                          {f.suggested_fix}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Created Issues & PRs */}
            {scanData?.actions && (
              <div className="grid gap-4 sm:grid-cols-2">
                {scanData.actions.issues.length > 0 && (
                  <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <AlertTriangle className="h-4 w-4 text-amber-600" />
                      Created Issues
                    </h3>
                    <div className="space-y-2">
                      {scanData.actions.issues.slice(0, 5).map((issue) => (
                        <a
                          key={issue.number}
                          href={issue.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 rounded-lg p-2 text-sm text-slate-700 transition hover:bg-slate-50"
                        >
                          <ExternalLink className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                          <span className="truncate">{issue.title}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                )}
                {scanData.actions.pull_requests.length > 0 && (
                  <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <GitPullRequest className="h-4 w-4 text-blue-600" />
                      Draft PRs
                    </h3>
                    <div className="space-y-2">
                      {scanData.actions.pull_requests.map((pr) => (
                        <a
                          key={pr.number}
                          href={pr.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 rounded-lg p-2 text-sm text-slate-700 transition hover:bg-slate-50"
                        >
                          <ExternalLink className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                          <span className="truncate">{pr.title}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Summary Issue Link */}
            {scanData?.actions?.summary_issue_url && (
              <a
                href={scanData.actions.summary_issue_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700"
              >
                <Github className="h-4 w-4" />
                View Full Health Report on GitHub
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
