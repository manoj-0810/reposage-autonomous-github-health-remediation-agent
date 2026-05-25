"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowLeft,
  Github,
  AlertTriangle,
  GitPullRequest,
  ExternalLink,
  Activity,
} from "lucide-react";

interface HistoryEntry {
  scan_id: string;
  scanned_at: string;
  health_score: number;
  security: number;
  dependencies: number;
  code_quality: number;
  test_coverage: number;
}

const COLORS = ["#ef4444", "#3b82f6", "#a855f7", "#10b981"];
const DIMENSION_LABELS = ["Security", "Dependencies", "Code Quality", "Test Coverage"];

export default function RepoDashboardPage() {
  const { owner, repo } = useParams() as { owner: string; repo: string };
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const decodedOwner = decodeURIComponent(owner);
  const decodedRepo = decodeURIComponent(repo);

  useEffect(() => {
    fetch(`/api/repos/${decodedOwner}/${decodedRepo}/history`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed to load history");
        return r.json();
      })
      .then((data: HistoryEntry[]) => {
        setHistory(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [decodedOwner, decodedRepo]);

  // Chart data: reverse chronological for line chart
  const lineData = [...history].reverse().map((h) => ({
    date: new Date(h.scanned_at).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    overall: Math.round(h.health_score),
    security: Math.round(h.security),
    dependencies: Math.round(h.dependencies),
    code_quality: Math.round(h.code_quality),
    test_coverage: Math.round(h.test_coverage),
  }));

  // Latest scan for donut
  const latest = history[0];
  const donutData = latest
    ? [
        { name: "Security", value: Math.round(latest.security) },
        { name: "Dependencies", value: Math.round(latest.dependencies) },
        { name: "Code Quality", value: Math.round(latest.code_quality) },
        { name: "Test Coverage", value: Math.round(latest.test_coverage) },
      ]
    : [];

  const scoreColor = (score: number) => {
    if (score >= 80) return "text-green-600";
    if (score >= 60) return "text-yellow-600";
    if (score >= 40) return "text-orange-600";
    return "text-red-600";
  };

  return (
    <main className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-6 py-4">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <Github className="h-6 w-6 text-slate-700" />
          <div>
            <h1 className="text-lg font-bold text-slate-900">
              {decodedOwner}/{decodedRepo}
            </h1>
            <p className="text-xs text-slate-500">Repository Health Dashboard</p>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        {loading && (
          <div className="flex h-64 items-center justify-center">
            <Activity className="h-6 w-6 animate-spin text-blue-600" />
          </div>
        )}
        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">
            {error}
          </div>
        )}

        {!loading && !error && (
          <>
            {/* Score Overview */}
            {latest && (
              <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[
                  { label: "Overall", value: Math.round(latest.health_score) },
                  { label: "Security", value: Math.round(latest.security) },
                  { label: "Dependencies", value: Math.round(latest.dependencies) },
                  { label: "Code Quality", value: Math.round(latest.code_quality) },
                ].map((s) => (
                  <div
                    key={s.label}
                    className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200"
                  >
                    <p className="text-xs font-medium text-slate-500">{s.label}</p>
                    <p
                      className={`mt-1 text-3xl font-extrabold ${scoreColor(s.value)}`}
                    >
                      {s.value}
                      <span className="text-sm font-normal text-slate-400">
                        /100
                      </span>
                    </p>
                  </div>
                ))}
              </div>
            )}

            {/* Charts */}
            <div className="mb-6 grid gap-6 lg:grid-cols-2">
              {/* Line Chart */}
              <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
                <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Health Score Over Time
                </h2>
                {lineData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <AreaChart data={lineData}>
                      <defs>
                        <linearGradient id="overallGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} width={30} />
                      <Tooltip
                        contentStyle={{
                          borderRadius: "8px",
                          border: "1px solid #e2e8f0",
                          fontSize: "12px",
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: "12px" }} />
                      <Area
                        type="monotone"
                        dataKey="overall"
                        stroke="#3b82f6"
                        fill="url(#overallGrad)"
                        strokeWidth={2}
                        name="Overall"
                      />
                      <Area
                        type="monotone"
                        dataKey="security"
                        stroke="#ef4444"
                        fill="none"
                        strokeWidth={1.5}
                        name="Security"
                      />
                      <Area
                        type="monotone"
                        dataKey="dependencies"
                        stroke="#3b82f6"
                        fill="none"
                        strokeWidth={1.5}
                        name="Dependencies"
                      />
                      <Area
                        type="monotone"
                        dataKey="code_quality"
                        stroke="#a855f7"
                        fill="none"
                        strokeWidth={1.5}
                        name="Code Quality"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[280px] items-center justify-center text-sm text-slate-400">
                    No historical data yet.
                  </div>
                )}
              </div>

              {/* Donut Chart */}
              <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
                <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Dimension Breakdown
                </h2>
                {donutData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie
                        data={donutData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={90}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {donutData.map((_, index) => (
                          <Cell key={index} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value: number) => [`${value}/100`, ""]}
                        contentStyle={{
                          borderRadius: "8px",
                          border: "1px solid #e2e8f0",
                          fontSize: "12px",
                        }}
                      />
                      <Legend
                        wrapperStyle={{ fontSize: "12px" }}
                        formatter={(_: any, entry: any) => entry.value}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[280px] items-center justify-center text-sm text-slate-400">
                    No data available.
                  </div>
                )}
              </div>
            </div>

            {/* Scan History Table */}
            <div className="rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
              <div className="border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Scan History
                </h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <tr>
                      <th className="px-5 py-3">Date</th>
                      <th className="px-5 py-3">Overall</th>
                      <th className="px-5 py-3">Security</th>
                      <th className="px-5 py-3">Deps</th>
                      <th className="px-5 py-3">Quality</th>
                      <th className="px-5 py-3">Coverage</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {history.map((h) => (
                      <tr key={h.scan_id} className="hover:bg-slate-50">
                        <td className="px-5 py-3 text-slate-700">
                          {new Date(h.scanned_at).toLocaleDateString("en-US", {
                            year: "numeric",
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </td>
                        <td className={`px-5 py-3 font-bold ${scoreColor(h.health_score)}`}>
                          {Math.round(h.health_score)}
                        </td>
                        <td className="px-5 py-3 text-slate-600">
                          {Math.round(h.security)}
                        </td>
                        <td className="px-5 py-3 text-slate-600">
                          {Math.round(h.dependencies)}
                        </td>
                        <td className="px-5 py-3 text-slate-600">
                          {Math.round(h.code_quality)}
                        </td>
                        <td className="px-5 py-3 text-slate-600">
                          {Math.round(h.test_coverage)}
                        </td>
                      </tr>
                    ))}
                    {history.length === 0 && (
                      <tr>
                        <td
                          colSpan={6}
                          className="px-5 py-8 text-center text-slate-400"
                        >
                          No scans recorded yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
