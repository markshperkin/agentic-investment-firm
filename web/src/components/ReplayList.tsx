import { useEffect, useState } from "react";
import { Approval, getApprovals, listRuns, RunSummary } from "../api";
import { relTime, shortId, statusKind, STATUS_LABEL } from "../format";
import NewReplayDialog from "./NewReplayDialog";

export default function ReplayList({
  selectedRunId,
  onSelect,
}: {
  selectedRunId: string | null;
  onSelect: (id: string) => void;
}) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [pending, setPending] = useState<Approval[]>([]);
  const [showNew, setShowNew] = useState(false);

  const refresh = () => {
    listRuns().then(setRuns);
    getApprovals("PENDING").then(setPending).catch(() => setPending([]));
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <div className="panel-head">
        <h3>Replays</h3>
        <button className="right" onClick={() => setShowNew(true)}>+ New</button>
      </div>
      {showNew && (
        <NewReplayDialog
          onClose={() => setShowNew(false)}
          onStarted={(id) => {
            setShowNew(false);
            refresh();
            onSelect(id);
          }}
        />
      )}
      <div className="list">
        {!runs.length && <div className="empty">No replays yet.<br />Start one with + New.</div>}
        {runs.map((r) => {
          const kind = statusKind(r, pending);
          return (
            <div
              key={r.id}
              className={"list-row" + (r.id === selectedRunId ? " selected" : "")}
              onClick={() => onSelect(r.id)}
            >
              <span className={`dot ${kind}`} title={STATUS_LABEL[kind]} />
              <div style={{ minWidth: 0 }}>
                <div className="title">{r.replay_date ?? "—"} · {shortId(r.id)}</div>
                <div className="sub">{STATUS_LABEL[kind]} · {relTime(r.started_at)}</div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
