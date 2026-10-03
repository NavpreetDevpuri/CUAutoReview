export function countLabel(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function runStatusLabel(run: { status?: unknown; processing_status?: unknown; archived?: unknown; archived_at?: unknown; progress?: unknown; failed_task_count?: unknown }) {
  if (run.archived || run.archived_at) return "archived";
  const status = String(run.status || run.processing_status || "unknown");
  const progress = run.progress && typeof run.progress === "object" ? run.progress as Record<string, unknown> : {};
  return status.toLowerCase() === "completed" && Number(progress.failed ?? run.failed_task_count ?? 0) > 0 ? "finished with errors" : status;
}

export function reviewProcessingError(value: unknown): string {
  const message = value === null || value === undefined ? "" : String(value);
  if (/invalid structured output|invalid json|schema validation|structured output file/i.test(message)) {
    const retryNote = /no (?:application )?retry was made/i.test(message) ? " No automatic retry was made." : "";
    return `The model response could not be parsed as the required review format (JSON). This is a review-processing error, separate from the original benchmark result.${retryNote}`;
  }
  return message || "No error reason recorded";
}

export function formatDate(value: unknown): string {
  if (!value) return "Not recorded";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function displayValue(value: unknown, fallback = "Not recorded"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}
