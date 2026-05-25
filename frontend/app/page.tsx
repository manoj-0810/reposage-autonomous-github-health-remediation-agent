"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Activity, ArrowRight, Github, Shield, Sparkles, Zap } from "lucide-react";

export default function HomePage() {
  const [repoUrl, setRepoUrl] = useState("");
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  const [recentRepos, setRecentRepos] = useState<{ owner: string; repo: string; score: number; scan_id: string }[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(true);

  useEffect(() => {
    fetch("/api/scans/recent")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch recent scans");
        return res.json();
      })
      .then((data) => {
        setRecentRepos(data);
        setLoadingRecent(false);
      })
      .catch((err) => {
        console.error(err);
        setLoadingRecent(false);
      });
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!repoUrl.trim()) {
      setError("Please enter a GitHub repository URL.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/scans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl, github_token: token }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to start scan");
      }
      const data = await res.json();
      router.push(`/scan/${data.scan_id}`);
    } catch (err: any) {
      setError(err.message || "Something went wrong.");
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50">
      {/* Hero Section */}
      <section className="relative overflow-hidden px-6 pt-20 pb-16 lg:pt-32 lg:pb-24">
        <div className="mx-auto max-w-5xl text-center">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-blue-50 px-4 py-1.5 text-sm font-medium text-blue-700 ring-1 ring-blue-200">
            <Sparkles className="h-4 w-4" />
            Autonomous Multi-Agent Pipeline
          </div>
          <h1 className="mb-6 text-4xl font-extrabold tracking-tight text-slate-900 sm:text-6xl lg:text-7xl">
            RepoSage
            <span className="block text-blue-600">GitHub Health Agent</span>
          </h1>
          <p className="mx-auto mb-10 max-w-2xl text-lg text-slate-600 sm:text-xl">
            Deep health audits for any GitHub repository. Our fleet of AI agents
            detects issues, prioritizes fixes, and automatically opens Issues &amp;
            draft PRs.
          </p>

          {/* Scan Form */}
          <form
            onSubmit={handleSubmit}
            className="mx-auto mb-16 flex max-w-2xl flex-col gap-4 rounded-2xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-200 sm:flex-row sm:items-end"
          >
            <div className="flex-1 space-y-3">
              <div>
                <label className="mb-1 block text-left text-sm font-medium text-slate-700">
                  GitHub Repository URL
                </label>
                <div className="relative">
                  <Github className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type="url"
                    required
                    placeholder="https://github.com/owner/repo"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 bg-slate-50 py-2.5 pl-10 pr-4 text-sm text-slate-900 placeholder-slate-400 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-left text-sm font-medium text-slate-700">
                  GitHub Personal Access Token{" "}
                  <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <input
                  type="password"
                  placeholder="ghp_xxxxxxxxxxxx"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-slate-50 py-2.5 px-4 text-sm text-slate-900 placeholder-slate-400 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-6 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? (
                <>
                  <Activity className="h-4 w-4 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  Run Scan
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>
          {error && (
            <p className="mx-auto -mt-12 mb-12 max-w-lg rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700 ring-1 ring-red-200">
              {error}
            </p>
          )}

          {/* Features */}
          <div className="grid gap-6 sm:grid-cols-3">
            {[
              {
                icon: <Shield className="h-6 w-6 text-blue-600" />,
                title: "Security Scanning",
                desc: "Detects secrets, eval(), SQL injection, and vulnerable dependencies.",
              },
              {
                icon: <Zap className="h-6 w-6 text-amber-600" />,
                title: "Auto-Fixes",
                desc: "Generates validated code patches and opens draft PRs automatically.",
              },
              {
                icon: <Activity className="h-6 w-6 text-emerald-600" />,
                title: "Real-time Feed",
                desc: "Watch every agent step live via Server-Sent Events as it runs.",
              },
            ].map((f) => (
              <div
                key={f.title}
                className="rounded-xl bg-white p-6 text-left shadow-sm ring-1 ring-slate-200 transition hover:shadow-md"
              >
                <div className="mb-3 inline-flex rounded-lg bg-slate-50 p-2">
                  {f.icon}
                </div>
                <h3 className="mb-1 text-sm font-semibold text-slate-900">
                  {f.title}
                </h3>
                <p className="text-sm text-slate-600">{f.desc}</p>
              </div>
            ))}
          </div>

          {/* Social Proof — Dynamic Recent Repos */}
          <div className="mt-16">
            <p className="mb-4 text-sm font-medium uppercase tracking-wider text-slate-500">
              Recently Scanned Repositories
            </p>
            {loadingRecent ? (
              <div className="flex justify-center py-4">
                <Activity className="h-5 w-5 animate-spin text-slate-400" />
              </div>
            ) : recentRepos.length > 0 ? (
              <div className="flex flex-wrap justify-center gap-3">
                {recentRepos.map((r) => (
                  <Link
                    key={`${r.owner}/${r.repo}`}
                    href={`/repo/${r.owner}/${r.repo}`}
                    className="group inline-flex items-center gap-3 rounded-full bg-white px-5 py-2.5 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-blue-300"
                  >
                    <Github className="h-4 w-4 text-slate-400 group-hover:text-blue-600" />
                    {r.owner}/{r.repo}
                    <span
                      className={`inline-flex h-6 items-center rounded-full px-2.5 text-xs font-bold ${
                        r.score >= 80
                          ? "bg-green-100 text-green-700"
                          : r.score >= 60
                          ? "bg-yellow-100 text-yellow-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {Math.round(r.score)}
                    </span>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-400">No repositories scanned yet. Be the first!</p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
