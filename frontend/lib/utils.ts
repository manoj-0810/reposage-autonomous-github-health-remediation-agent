import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getSeverityColor(severity: string): string {
  switch (severity) {
    case "critical":
      return "text-critical bg-red-50 border-red-200";
    case "high":
      return "text-high bg-orange-50 border-orange-200";
    case "medium":
      return "text-medium bg-yellow-50 border-yellow-200";
    case "low":
      return "text-low bg-green-50 border-green-200";
    default:
      return "text-gray-700 bg-gray-50 border-gray-200";
  }
}

export function getSeverityDot(severity: string): string {
  switch (severity) {
    case "critical":
      return "bg-critical";
    case "high":
      return "bg-high";
    case "medium":
      return "bg-medium";
    case "low":
      return "bg-low";
    default:
      return "bg-gray-400";
  }
}

export function getScoreColor(score: number): string {
  if (score >= 80) return "text-green-600";
  if (score >= 60) return "text-yellow-600";
  if (score >= 40) return "text-orange-600";
  return "text-red-600";
}

export function getScoreRingColor(score: number): string {
  if (score >= 80) return "stroke-green-500";
  if (score >= 60) return "stroke-yellow-500";
  if (score >= 40) return "stroke-orange-500";
  return "stroke-red-500";
}
