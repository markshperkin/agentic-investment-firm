import { useState } from "react";
import { Approval, SpanEvent } from "../api";
import { stepStatusClass } from "../format";
import CommitteeReview from "./CommitteeReview";
import DataView from "./DataView";
import HitlActions from "./HitlActions";

function metric(e: SpanEvent): string {
  const parts: string[] = [];
  if (e.model) parts.push(e.model);
  if (e.prompt_tokens || e.completion_tokens) {
    parts.push(`in ${e.prompt_tokens.toLocaleString()} · out ${e.completion_tokens.toLocaleString()} tok`);
  }
  if (e.cost_usd > 0) parts.push(`$${e.cost_usd.toFixed(4)}`);
  if (e.latency_ms != null) parts.push(`${e.latency_ms}ms`);
  return parts.join(" · ");
}

export default function StepRow({
  e,
  depth,
  approval,
  onDecided,
}: {
  e: SpanEvent;
  depth: number;
  approval?: Approval;
  onDecided: () => void;
}) {
  // The HITL committee step (await_approval) is shown as one "Committee decision" step.
  // Its live state comes from the approval status, not the span (which stays PENDING).
  const isCommittee = e.kind === "HITL" && e.name === "await_approval";
  const pending = approval?.status === "PENDING";
  const [open, setOpen] = useState(isCommittee && pending);

  const cls = isCommittee ? (pending ? "working" : "ok") : stepStatusClass(e.status);
  const hasDetail = isCommittee ? !!approval : e.input != null || e.output != null || e.error != null;
  const statusLabel = cls === "working" ? "working…" : cls === "ok" ? "done" : cls === "error" ? "ERROR" : e.status;
  const label = isCommittee ? "Committee decision" : e.name.startsWith("llm:") ? e.name.slice(4) : e.name;

  return (
    <div
      className="step"
      style={{
        marginLeft: depth * 14,
        paddingLeft: depth > 0 ? 10 : 16,
        borderLeft: depth > 0 ? "2px solid var(--border-soft)" : undefined,
      }}
    >
      <div className="step-row">
        <span className={`dot ${cls === "ok" ? "finished" : cls === "working" ? "pending" : cls === "error" ? "error" : "halted"}`} />
        <span className="label">{label}</span>
        {!isCommittee && e.agent && <span className="agent">{e.agent}</span>}
        {e.ticker && <span className="badge">{e.ticker}</span>}
        <span className={`status-text ${cls}`} style={{ fontSize: 12 }}>
          {statusLabel}
        </span>
        <span className="metric right">{metric(e)}</span>
        {hasDetail && (
          <button className="step-toggle" onClick={() => setOpen(!open)}>
            {open ? "less" : "read more"}
          </button>
        )}
      </div>

      {e.error && <div className="neg" style={{ marginTop: 4 }}>{e.error}</div>}

      {/* HITL: always-visible action bar (pending) or outcome (resolved) */}
      {isCommittee && approval && <HitlActions approval={approval} onDecided={onDecided} />}

      {open && hasDetail && (
        isCommittee && approval ? (
          <div className="detail">
            <div className="detail-block">
              <CommitteeReview approval={approval} />
            </div>
          </div>
        ) : (
          <div className="detail">
            {e.input != null && (
              <div className="detail-block">
                <div className="json-label">input</div>
                <DataView value={e.input} />
              </div>
            )}
            {e.output != null && (
              <div className="detail-block">
                <div className="json-label">output</div>
                <DataView value={e.output} />
              </div>
            )}
          </div>
        )
      )}
    </div>
  );
}
