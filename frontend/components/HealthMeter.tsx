"use client";

import { useEffect, useState } from "react";
import { getScoreRingColor } from "@/lib/utils";

interface HealthMeterProps {
  score: number;
  size?: number;
}

export default function HealthMeter({ score, size = 140 }: HealthMeterProps) {
  const [animatedScore, setAnimatedScore] = useState(0);
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (animatedScore / 100) * circumference;

  useEffect(() => {
    const timer = setTimeout(() => setAnimatedScore(score), 100);
    return () => clearTimeout(timer);
  }, [score]);

  const colorClass = getScoreRingColor(score);

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth={strokeWidth}
        />
        {/* Score ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          className={`${colorClass} transition-all duration-1000 ease-out`}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className={`text-2xl font-extrabold tabular-nums ${
            score >= 80
              ? "text-green-600"
              : score >= 60
              ? "text-yellow-600"
              : score >= 40
              ? "text-orange-600"
              : "text-red-600"
          }`}
        >
          {Math.round(animatedScore)}
        </span>
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
          /100
        </span>
      </div>
    </div>
  );
}
