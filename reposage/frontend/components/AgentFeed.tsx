"use client";

import { useEffect, useRef } from "react";
import {
  CheckCircle2,
  Loader2,
  Play,
  XCircle,
} from "lucide-react";

interface AgentEvent {
  agent: string;
  status: "pending" | "running" | "done" | "error";
  message: string;
  timestamp: string;
}

interface AgentFeedProps {
  events: AgentEvent[];
  steps: { key: string; label: string }[];
}

export default function AgentFeed({ events, steps }: AgentFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const agentStatus = (agentKey: string) => {
    const ev = events.filter((e) => e.agent === agentKey).pop();
    if (!ev) return "pending";
    return ev.status;
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "done":
        return <CheckCircle2 className="h-5 w-5 text-green-600" />;
      case "running":
        return <Loader2 className="h-5 w-5 animate-spin text-blue-600" />;
      case "error":
        return <XCircle className="h-5 w-5 text-red-500" />;
      default:
        return (
          <div className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-slate-300">
            <div className="h-1.5 w-1.5 rounded-full bg-slate-300" />
          </div>
        );
    }
  };

  return (
    <div className="rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      {/* Agent Steps */}
      <div className="border-b border-slate-100 px-5 py-4">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Agent Pipeline
        </h3>
        <div className="space-y-2">
          {steps.map((step) => {
            const status = agentStatus(step.key);
            return (
              <div
                key={step.key}
                className="flex items-center gap-3 rounded-lg p-2 transition hover:bg-slate-50"
              >
                <div className="flex h-7 w-7 shrink-0 items-center justify-center">
                  {getStatusIcon(status)}
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
              </div>
            );
          })}
        </div>
      </div>

      {/* Live Log */}
      <div className="px-5 py-3">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Live Log
        </h3>
        <div className="h-64 overflow-y-auto custom-scrollbar space-y-1.5 pr-1">
          {events.length === 0 && (
            <p className="py-8 text-center text-xs text-slate-400">
              Waiting for agents to start…
            </p>
          )}
          {events.map((ev, i) => (
            <div
              key={i}
              className="animate-slide-in rounded-md bg-slate-50 px-2.5 py-1.5"
            >
              <div className="flex items-center gap-1.5">
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
                <span className="text-xs font-semibold text-slate-700">
                  {ev.agent}
                </span>
                <span className="text-[10px] text-slate-400">
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <p className="pl-3 text-xs text-slate-600">{ev.message}</p>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
