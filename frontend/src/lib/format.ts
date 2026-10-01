import type { CaseStatus, CategorySelection } from "../api/types";

/** Friendly labels for lifecycle statuses (the API uses the compact names). */
export const STATUS_LABELS: Record<CaseStatus, string> = {
  Intake: "Intake",
  EnrichmentFailed: "Enrichment failed",
  Queued: "Queued",
  AssignedAgent: "Assigned to agent",
  AssignedAI: "Assigned to AI",
  WaitingApproval: "Waiting for approval",
  WaitingOnCustomer: "Waiting on customer",
  Solved: "Solved",
  Closed: "Closed",
};

/** Button labels: what an agent is *doing* when moving a case to that status. */
export const STATUS_ACTIONS: Record<CaseStatus, string> = {
  Intake: "Retry enrichment",
  EnrichmentFailed: "Mark enrichment failed",
  Queued: "Move to queue",
  AssignedAgent: "Assign to me",
  AssignedAI: "Assign to AI",
  WaitingApproval: "Request approval",
  WaitingOnCustomer: "Wait on customer",
  Solved: "Mark solved",
  Closed: "Close case",
};

const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateTime.format(date);
}

export function formatCategory(category: CategorySelection | null | undefined): string {
  if (!category) return "Uncategorized";
  return [category.type, category.category, category.subcategory].filter(Boolean).join(" › ");
}

/**
 * Case numbers are Unix timestamps in microseconds (backend/app/domain/ids.py),
 * shown in full, e.g. 1790812345678901.
 */
export function formatCaseNumber(caseNumber: number): string {
  return String(caseNumber);
}

/** Parse a case number from a URL segment; null if it isn't one. */
export function parseCaseNumber(text: string | undefined): number | null {
  if (!text || !/^\d{1,16}$/.test(text)) return null;
  const value = Number(text);
  return Number.isSafeInteger(value) ? value : null;
}

/** Compact age since a timestamp: "just now", "45m", "3h", "2d". */
export function formatAge(iso: string, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (Number.isNaN(minutes)) return "—";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}
