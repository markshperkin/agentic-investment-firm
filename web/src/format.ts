import { Approval, RunSummary } from "./api";

export type StatusKind = "running" | "pending" | "finished" | "halted" | "error";

export function statusKind(run: RunSummary, pending: Approval[]): StatusKind {
  const s = (run.status || "").toUpperCase();
  if (s === "DONE") return "finished";
  if (s === "HALTED") return "halted";
  if (s === "ERROR") return "error";
  // RUNNING — pending if it has an approval awaiting a human decision
  if (pending.some((a) => a.run_id === run.id)) return "pending";
  return "running";
}

export const STATUS_LABEL: Record<StatusKind, string> = {
  running: "running",
  pending: "pending",
  finished: "finished",
  halted: "halted",
  error: "error",
};

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function pct(x: number | null | undefined): string {
  return x == null ? "—" : `${(x * 100).toFixed(2)}%`;
}

export function money(x: number | null | undefined, dp = 0): string {
  if (x == null) return "—";
  return `$${x.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
}

export function relTime(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function clockTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// span status -> step visual class
export function stepStatusClass(status: string): "ok" | "working" | "error" | "idle" {
  if (status === "OK") return "ok";
  if (status === "ERROR") return "error";
  if (status === "PENDING") return "working";
  return "idle";
}
