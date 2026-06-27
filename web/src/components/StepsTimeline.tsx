import { useEffect, useMemo, useState } from "react";
import { Approval, getFeed, getRunApprovals, openStream, SpanEvent } from "../api";
import { clockTime, stepStatusClass } from "../format";
import StepRow from "./StepRow";

// The HITL flow emits await_approval + paused + decision spans; collapse to the single
// await_approval, shown as one "Committee decision" step.
const HIDDEN_HITL = new Set(["paused", "decision"]);

interface Phase {
  key: string;
  tickSeq: number | null;
  header: SpanEvent | null;
  steps: SpanEvent[];
}

interface Node {
  span: SpanEvent;
  children: Node[];
}

// HITL wait spans are persisted as PENDING forever, so their live state comes from
// whether the approval is still pending — not from the raw span status.
function effective(s: SpanEvent, pendingIds: Set<string>): "ok" | "working" | "error" | "idle" {
  if (s.kind === "HITL" && (s.name === "await_approval" || s.name === "paused")) {
    return s.trade_id && pendingIds.has(s.trade_id) ? "working" : "ok";
  }
  return stepStatusClass(s.status);
}

function rollup(p: Phase, pendingIds: Set<string>): "ok" | "working" | "error" | "idle" {
  const es = [...(p.header ? [p.header] : []), ...p.steps].map((s) => effective(s, pendingIds));
  if (es.includes("working")) return "working";
  if (es.includes("error")) return "error";
  if (es.length) return "ok";
  return "idle";
}

// Build the span tree for a phase and fold each agent's own LLM call into it, so one
// logical step = one row (the llm:* implementation span is merged, not shown twice).
function buildTree(steps: SpanEvent[]): Node[] {
  const nodes = new Map(steps.map((s) => [s.id, { span: s, children: [] as Node[] }]));
  const roots: Node[] = [];
  const ordered = [...steps].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? ""));
  for (const s of ordered) {
    const node = nodes.get(s.id)!;
    const parent = s.parent_span_id ? nodes.get(s.parent_span_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots.map(fold);
}

function fold(node: Node): Node {
  let span = node.span;
  let children = node.children;
  if (span.kind === "AGENT") {
    const i = children.findIndex((c) => c.span.kind === "LLM" && c.span.agent === span.agent);
    if (i >= 0) {
      const llm = children[i].span;
      span = {
        ...span,
        model: llm.model,
        prompt_tokens: llm.prompt_tokens,
        completion_tokens: llm.completion_tokens,
        cost_usd: llm.cost_usd,
        latency_ms: span.latency_ms ?? llm.latency_ms,
        input: span.input ?? llm.input,
        output: span.output ?? llm.output,
      };
      children = children.filter((_, j) => j !== i).concat(children[i].children);
    }
  }
  return { span, children: children.map(fold) };
}

export default function StepsTimeline({ runId }: { runId: string }) {
  const [spans, setSpans] = useState<SpanEvent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [manual, setManual] = useState<Record<string, boolean>>({});

  const reload = () => {
    getFeed(runId).then(setSpans);
    getRunApprovals(runId).then(setApprovals).catch(() => setApprovals([]));
  };

  useEffect(() => {
    setManual({});
    reload();
    const ws = openStream((e) => {
      if (e.run_id !== runId) return;
      setSpans((prev) => {
        const i = prev.findIndex((p) => p.id === e.id);
        if (i >= 0) {
          const next = prev.slice();
          next[i] = e;
          return next;
        }
        return [...prev, e];
      });
    });
    const t = setInterval(() => {
      getRunApprovals(runId).then(setApprovals).catch(() => {});
    }, 3000);
    return () => {
      ws.close();
      clearInterval(t);
    };
  }, [runId]);

  const pendingIds = useMemo(
    () => new Set(approvals.filter((a) => a.status === "PENDING").map((a) => a.id)),
    [approvals],
  );
  const approvalFor = (span: SpanEvent): Approval | undefined =>
    span.trade_id ? approvals.find((a) => a.id === span.trade_id) : undefined;

  const phases = useMemo(() => {
    const map = new Map<string, Phase>();
    const keyOf = (s: SpanEvent) => (s.tick_seq != null ? `t${s.tick_seq}` : "misc");
    const ordered = [...spans].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? ""));
    for (const s of ordered) {
      if (s.kind === "HITL" && HIDDEN_HITL.has(s.name)) continue;
      const key = keyOf(s);
      if (!map.has(key)) map.set(key, { key, tickSeq: s.tick_seq, header: null, steps: [] });
      const ph = map.get(key)!;
      if (s.kind === "TICK") ph.header = s;
      else ph.steps.push(s);
    }
    return [...map.values()].sort((a, b) => (a.tickSeq ?? 999) - (b.tickSeq ?? 999));
  }, [spans]);

  const renderNode = (node: Node, depth: number) => (
    <div key={node.span.id}>
      <StepRow e={node.span} depth={depth} approval={approvalFor(node.span)} onDecided={reload} />
      {node.children.map((c) => renderNode(c, depth + 1))}
    </div>
  );

  if (!spans.length) return <div className="empty">No steps yet — waiting for the run to emit spans.</div>;

  return (
    <div>
      {phases.map((p, idx) => {
        const status = rollup(p, pendingIds);
        const isLast = idx === phases.length - 1;
        const open = p.key in manual ? manual[p.key] : status === "working" || isLast;
        const dotCls = status === "ok" ? "finished" : status === "working" ? "pending" : status === "error" ? "error" : "halted";
        const tree = buildTree(p.steps);
        return (
          <div className="phase" key={p.key}>
            <div className="phase-head" onClick={() => setManual((m) => ({ ...m, [p.key]: !open }))}>
              <span className={`dot ${dotCls}`} />
              <span className="path">{p.header?.name ?? "tick"}</span>
              <span className="meta">
                {p.tickSeq != null ? `t${p.tickSeq}` : "—"}
                {p.header?.as_of ? ` · ${clockTime(p.header.as_of)}` : ""}
              </span>
              <span className="meta right">{p.steps.length} step{p.steps.length === 1 ? "" : "s"} · {open ? "▾" : "▸"}</span>
            </div>
            {open && (
              <div className="phase-body">
                {tree.map((n) => renderNode(n, 0))}
                {!tree.length && <div className="step faint">no child steps</div>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
