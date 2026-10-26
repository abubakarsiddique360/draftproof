const STATUS_LABELS = {
  queued: "Queued",
  running: "Running",
  awaiting_review: "Awaiting review",
  revising: "Revising",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] ?? String(status ?? "unknown").replace(/_/g, " ");
}

export function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} kB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatNumber(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(Number(value) || 0);
}

export function formatCost(value) {
  const amount = Number(value) || 0;
  if (amount === 0) return "$0.00";
  if (amount < 0.01) return `$${amount.toFixed(4)}`;
  return `$${amount.toFixed(2)}`;
}

export function formatDuration(ms) {
  const value = Number(ms) || 0;
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.floor(value / 60_000)}m ${Math.round((value % 60_000) / 1000)}s`;
}

export function formatTime(iso, now = Date.now()) {
  if (!iso) return "—";
  const stamp = Date.parse(iso);
  if (Number.isNaN(stamp)) return "—";
  const date = new Date(stamp);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function relativeTime(iso, now = Date.now()) {
  const stamp = Date.parse(iso);
  if (Number.isNaN(stamp)) return "—";
  const seconds = Math.round((now - stamp) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  const days = Math.round(seconds / 86_400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function scoreTone(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) return "idle";
  if (value >= 80) return "pass";
  if (value >= 65) return "warn";
  return "fail";
}

export function gradeFor(score) {
  const value = Number(score) || 0;
  if (value >= 90) return "A";
  if (value >= 80) return "B";
  if (value >= 70) return "C";
  if (value >= 60) return "D";
  return "F";
}

export function truncate(text, limit = 120) {
  const value = String(text ?? "");
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

export function titleCase(value) {
  return String(value ?? "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function isTerminal(status) {
  return ["completed", "failed", "cancelled"].includes(status);
}

export function summarizeEvent(event) {
  const data = event && typeof event.data === "object" && event.data !== null ? event.data : {};
  switch (event?.type) {
    case "run_started":
      return `Run started for “${truncate(data.topic ?? "", 70)}”`;
    case "log":
      return data.message ?? "log";
    case "warning":
      return data.message ?? "warning";
    case "stage_started":
      return `Stage ${data.stage} started`;
    case "stage_finished":
      return `Stage ${data.stage} finished in ${formatDuration(data.duration_ms)}`;
    case "outline_ready":
      return `Outline ready: ${data.title ?? "untitled"} (${(data.sections ?? []).length} sections)`;
    case "evidence_ready":
      return `${data.count ?? 0} sources selected from ${data.candidates ?? data.count ?? 0} candidates`;
    case "section_ready":
      return `Section ${data.section_id} drafted (${data.words ?? 0} words)`;
    case "claims_ready":
      return `${data.claims ?? 0} claims extracted from ${data.section_id}`;
    case "verification_ready":
      return `${data.verified_claims ?? 0}/${data.total_claims ?? 0} claims verified (${Math.round((data.coverage ?? 0) * 100)}%)`;
    case "quality_scored":
      return `Quality ${Number(data.score ?? 0).toFixed(1)} (${data.grade ?? "?"}) — ${data.passed ? "gates passed" : "gates failed: " + (data.failed_gates ?? []).join(", ")}`;
    case "revision_started":
      return `Revision ${data.attempt} on ${(data.sections ?? []).length} section(s)`;
    case "revision_finished":
      return `Revision ${data.attempt} scored ${Number(data.score ?? 0).toFixed(1)}`;
    case "artifact_written":
      return `Artifact written: ${data.kind} (${formatBytes(data.bytes)})`;
    case "usage":
      return `${formatNumber(data.total_tokens ?? (data.prompt_tokens ?? 0) + (data.completion_tokens ?? 0))} tokens, ${data.calls ?? 0} calls, ${formatCost(data.cost_usd)}`;
    case "run_finished":
      return `Run ${statusLabel(data.status)}${data.error ? `: ${data.error}` : ""}`;
    case "run_status":
      return `Run status: ${statusLabel(data.status)}`;
    case "stream_end":
      return "Live stream closed";
    default:
      return event?.type ?? "event";
  }
}

export function eventLevel(event) {
  const data = event && typeof event.data === "object" && event.data !== null ? event.data : {};
  if (event?.type === "warning") return "warn";
  if (data.level === "error") return "error";
  if (event?.type === "run_finished" && data.status === "failed") return "error";
  return "info";
}
