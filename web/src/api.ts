export interface SpanEvent {
  id: string;
  run_id: string;
  parent_span_id: string | null;
  tick_seq: number | null;
  as_of: string | null;
  kind: string;
  name: string;
  agent: string | null;
  tool: string | null;
  ticker: string | null;
  trade_id: string | null;
  input: unknown;
  output: unknown;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  cache_hit: boolean | null;
  status: string;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface RunSummary {
  id: string;
  kind: string;
  replay_date: string | null;
  status: string;
  started_at: string | null;
}

export interface Holding {
  ticker: string;
  quantity: number;
  avg_cost_basis: number;
  realized_pnl: number;
}

export interface PortfolioState {
  cash: number;
  currency: string;
  holdings: Holding[];
  equity_at_cost: number;
}

export interface TickerStats {
  ticker: string;
  prices: {
    status: string;
    interval?: string;
    n_bars?: number;
    n_bars_current_day?: number;
    n_bars_lookback?: number;
  };
  corpus_status: string;
  filings: { current_day: number; prior_7d: number; older: number; total: number };
  chunks: { current_day: number; prior_7d: number; total: number };
  warnings: string[];
}

export interface DatasetDay {
  replay_date: string;
  tickers: string[];
  stats: TickerStats[];
}

export async function listRuns(): Promise<RunSummary[]> {
  const r = await fetch("/runs");
  return r.json();
}

export async function getDatasets(): Promise<DatasetDay[]> {
  const r = await fetch("/datasets");
  return r.json();
}

export async function ingestDataset(date: string, tickers: string[]): Promise<unknown> {
  const r = await fetch("/datasets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date, tickers }),
  });
  return r.json();
}

export async function ingestDemoDataset(): Promise<{ date: string }> {
  const r = await fetch("/datasets/demo", { method: "POST" });
  if (!r.ok) throw new Error((await r.json()).detail ?? "demo ingest failed");
  return r.json();
}

export async function deleteAllDatasets(): Promise<unknown> {
  const r = await fetch("/admin/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true, drop_corpus: true, drop_prices: true }),
  });
  return r.json();
}

export async function runReplay(date: string, tickers: string[]): Promise<{ run_id: string }> {
  const r = await fetch("/run/replay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date, tickers }),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? "run failed");
  return r.json();
}

export async function getPortfolio(): Promise<PortfolioState> {
  const r = await fetch("/portfolio");
  return r.json();
}

export async function getFeed(runId: string): Promise<SpanEvent[]> {
  const r = await fetch(`/runs/${runId}/feed`);
  return r.json();
}

export interface Approval {
  id: string;
  run_id: string;
  ticker: string;
  side: string;
  quantity: number;
  est_notional: number;
  reference_price: number;
  as_of: string;
  status: string;
  thesis_card: any;
  risk_reasoning: string | null;
  risk_severity: string | null;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  decision: string | null;
  approver: string | null;
  reject_reason: string | null;
  edited_quantity: number | null;
}

export async function getApprovals(status = "PENDING"): Promise<Approval[]> {
  const r = await fetch(`/approvals?status=${status}`);
  return r.json();
}

export async function getRunApprovals(runId: string): Promise<Approval[]> {
  const r = await fetch(`/approvals?status=ALL&run_id=${runId}`);
  return r.json();
}

export async function decideApproval(
  id: string,
  decision: "approve" | "edit" | "reject",
  editedQuantity?: number,
): Promise<any> {
  const r = await fetch(`/approvals/${id}/decide`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, approver: "operator", edited_quantity: editedQuantity ?? null }),
  });
  return r.json();
}

export async function getReport(runId: string): Promise<any> {
  const r = await fetch(`/runs/${runId}/report`);
  return r.json();
}

export async function getCost(runId: string): Promise<any> {
  const r = await fetch(`/runs/${runId}/cost`);
  return r.json();
}

export async function resetStore(): Promise<unknown> {
  const r = await fetch("/admin/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  });
  return r.json();
}

export function exportUrl(runId: string): string {
  return `/runs/${runId}/export`;
}

export function reportXlsxUrl(runId: string): string {
  return `/runs/${runId}/report.xlsx`;
}

export function openStream(onEvent: (e: SpanEvent) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/stream`);
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data) as SpanEvent);
  return ws;
}
