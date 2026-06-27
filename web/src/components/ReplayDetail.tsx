import { useEffect, useRef, useState } from "react";
import { Approval, getApprovals, listRuns, RunSummary } from "../api";
import { shortId, statusKind, STATUS_LABEL } from "../format";
import { prefetchReport } from "../reports";
import StepsTimeline from "./StepsTimeline";
import PortfolioPanel from "./PortfolioPanel";
import ReportPanel from "./ReportPanel";
import CostPanel from "./CostPanel";

type Sub = "steps" | "portfolio" | "report" | "cost";
const SUBS: { id: Sub; label: string }[] = [
  { id: "steps", label: "Steps" },
  { id: "portfolio", label: "Portfolio" },
  { id: "report", label: "Report" },
  { id: "cost", label: "Cost" },
];

export default function ReplayDetail({ runId }: { runId: string }) {
  const [sub, setSub] = useState<Sub>("steps");
  const [run, setRun] = useState<RunSummary | null>(null);
  const [pending, setPending] = useState<Approval[]>([]);
  const finalizedRef = useRef<string | null>(null);

  useEffect(() => {
    const load = () => {
      listRuns().then((rs) => setRun(rs.find((r) => r.id === runId) ?? null));
      getApprovals("PENDING").then(setPending).catch(() => setPending([]));
    };
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [runId]);

  const kind = run ? statusKind(run, pending) : "running";

  // Warm the report cache so the Report tab is ready when opened: once on open, and
  // again the moment the run finishes (final numbers).
  useEffect(() => {
    prefetchReport(runId).catch(() => {});
  }, [runId]);
  useEffect(() => {
    if (kind === "finished" && finalizedRef.current !== runId) {
      finalizedRef.current = runId;
      prefetchReport(runId).catch(() => {});
    }
  }, [kind, runId]);

  return (
    <div>
      <div className="detail-head">
        <span className={`dot ${kind}`} />
        <h2 className="mono">{run?.replay_date ?? "—"} · {shortId(runId)}</h2>
        <span className={`status-text ${kind === "finished" ? "ok" : kind === "running" || kind === "pending" ? "working" : kind === "error" ? "error" : "idle"}`}>
          {STATUS_LABEL[kind]}
        </span>
      </div>

      <div className="subtabs">
        {SUBS.map((s) => (
          <button key={s.id} className={sub === s.id ? "active" : ""} onClick={() => setSub(s.id)}>
            {s.label}
          </button>
        ))}
      </div>

      {sub === "steps" && <StepsTimeline runId={runId} />}
      {sub === "portfolio" && <PortfolioPanel />}
      {sub === "report" && <ReportPanel runId={runId} />}
      {sub === "cost" && <CostPanel runId={runId} />}
    </div>
  );
}
