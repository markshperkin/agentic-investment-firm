export interface SpanEvent {
  id: string;
  run_id: string;
  parent_span_id: string | null;
  tick_seq: number | null;
  as_of: string | null;
  kind: string;
  name: string;
  agent: string | null;
  ticker: string | null;
  trade_id: string | null;
  output: unknown;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  status: string;
  error: string | null;
  started_at: string | null;
}

export interface RunSummary {
  id: string;
  kind: string;
  replay_date: string | null;
  status: string;
  started_at: string | null;
}

export async function listRuns(): Promise<RunSummary[]> {
  const r = await fetch("/runs");
  return r.json();
}

export async function getFeed(runId: string): Promise<SpanEvent[]> {
  const r = await fetch(`/runs/${runId}/feed`);
  return r.json();
}

export function openStream(onEvent: (e: SpanEvent) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/stream`);
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data) as SpanEvent);
  return ws;
}
