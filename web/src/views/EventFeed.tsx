import { useEffect, useState } from "react";
import { getFeed, listRuns, openStream, SpanEvent } from "../api";

function EventRow({ e }: { e: SpanEvent }) {
  const [open, setOpen] = useState(false);
  const indent = e.parent_span_id ? 20 : 0;
  const hasOutput = e.output != null;
  return (
    <div style={{ marginLeft: indent, padding: "4px 0", borderBottom: "1px solid #eee" }}>
      <span style={{ color: "#888", fontFamily: "monospace" }}>
        {e.as_of ?? ""} {e.tick_seq != null ? `t${e.tick_seq}` : ""}
      </span>{" "}
      <strong>{e.kind}</strong> · {e.name}{" "}
      <StatusBadge status={e.status} />
      {e.latency_ms != null && <span style={{ color: "#aaa" }}> · {e.latency_ms}ms</span>}
      {(e.prompt_tokens > 0 || e.completion_tokens > 0) && (
        <span style={{ color: "#aaa" }}>
          {" "}· in {e.prompt_tokens} / out {e.completion_tokens} tok
        </span>
      )}
      {e.cost_usd > 0 && <span style={{ color: "#aaa" }}> · ${e.cost_usd.toFixed(4)}</span>}
      {hasOutput && (
        <button onClick={() => setOpen(!open)} style={{ marginLeft: 8 }}>
          {open ? "hide output" : "show output"}
        </button>
      )}
      {open && hasOutput && (
        <pre style={{ background: "#f6f8fa", padding: 8, overflowX: "auto" }}>
          {JSON.stringify(e.output, null, 2)}
        </pre>
      )}
      {e.error && <div style={{ color: "#c00" }}>{e.error}</div>}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "OK" ? "#2a7" : status === "ERROR" ? "#c00" : status === "PENDING" ? "#e90" : "#888";
  return <span style={{ color, fontWeight: 600 }}>{status === "PENDING" ? "working…" : status}</span>;
}

export default function EventFeed() {
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<SpanEvent[]>([]);

  useEffect(() => {
    listRuns().then((runs) => {
      if (runs.length) setRunId(runs[0].id);
    });
  }, []);

  useEffect(() => {
    if (!runId) return;
    getFeed(runId).then(setEvents);
    const ws = openStream((e) => {
      if (e.run_id !== runId) return;
      setEvents((prev) => {
        const i = prev.findIndex((p) => p.id === e.id);
        if (i >= 0) {
          const next = prev.slice();
          next[i] = e;
          return next;
        }
        return [...prev, e];
      });
    });
    return () => ws.close();
  }, [runId]);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", fontFamily: "system-ui" }}>
      <h2>Event Feed {runId && <span style={{ color: "#aaa", fontSize: 14 }}>· {runId.slice(0, 8)}</span>}</h2>
      {!runId && <p>No runs yet. Trigger a replay to see the firm work.</p>}
      {events.map((e) => (
        <EventRow key={e.id} e={e} />
      ))}
    </div>
  );
}
