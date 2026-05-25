"use client";

import { AlertTriangle, FileCode2, Lightbulb } from "lucide-react";
import { getSeverityColor, getSeverityDot } from "@/lib/utils";

interface FindingCardProps {
  severity: string;
  category: string;
  filePath: string;
  lineRange?: [number, number] | null;
  description: string;
  suggestedFix?: string;
}

export default function FindingCard({
  severity,
  category,
  filePath,
  lineRange,
  description,
  suggestedFix,
}: FindingCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold ${getSeverityColor(
            severity
          )}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${getSeverityDot(severity)}`} />
          {severity}
        </span>
        <span className="text-xs font-medium uppercase tracking-wider text-slate-500">
          {category}
        </span>
      </div>

      <div className="mb-2 flex items-center gap-2 text-sm text-slate-700">
        <FileCode2 className="h-4 w-4 text-slate-400" />
        <span className="font-mono font-medium">{filePath}</span>
        {lineRange && (
          <span className="text-xs text-slate-400">
            :{lineRange[0]}-{lineRange[1]}
          </span>
        )}
      </div>

      <p className="mb-2 text-sm leading-relaxed text-slate-700">
        <AlertTriangle className="mr-1 inline h-3.5 w-3.5 text-amber-500" />
        {description}
      </p>

      {suggestedFix && (
        <div className="rounded-md bg-blue-50 px-3 py-2">
          <p className="flex items-start gap-1.5 text-xs text-blue-700">
            <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              <span className="font-semibold">Suggested fix:</span> {suggestedFix}
            </span>
          </p>
        </div>
      )}
    </div>
  );
}
