import { useEffect, useState } from "react";
import { DatasetDay, getDatasets, runReplay } from "../api";

export default function NewReplayDialog({
  onClose,
  onStarted,
}: {
  onClose: () => void;
  onStarted: (runId: string) => void;
}) {
  const [days, setDays] = useState<DatasetDay[]>([]);
  const [date, setDate] = useState("");
  const [symbols, setSymbols] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getDatasets().then((d) => {
      setDays(d);
      if (d.length) {
        setDate(d[0].replay_date);
        setSymbols(d[0].tickers.join(", "));
      }
    });
  }, []);

  const onPickDay = (replayDate: string) => {
    setDate(replayDate);
    const day = days.find((d) => d.replay_date === replayDate);
    if (day) setSymbols(day.tickers.join(", "));
  };

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const tickers = symbols.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
      const { run_id } = await runReplay(date, tickers);
      onStarted(run_id);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ margin: 12 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <strong>New replay</strong>
        <button className="right" onClick={onClose}>✕</button>
      </div>
      {days.length > 0 && (
        <label style={{ display: "block", marginBottom: 8 }}>
          <div className="faint" style={{ fontSize: 11, marginBottom: 2 }}>READY DAY</div>
          <select value={date} onChange={(e) => onPickDay(e.target.value)} style={{ width: "100%" }}>
            {days.map((d) => (
              <option key={d.replay_date} value={d.replay_date}>
                {d.replay_date} ({d.tickers.length} ticker{d.tickers.length === 1 ? "" : "s"})
              </option>
            ))}
          </select>
        </label>
      )}
      <label style={{ display: "block", marginBottom: 8 }}>
        <div className="faint" style={{ fontSize: 11, marginBottom: 2 }}>DATE</div>
        <input value={date} onChange={(e) => setDate(e.target.value)} style={{ width: "100%" }} placeholder="2024-05-23" />
      </label>
      <label style={{ display: "block", marginBottom: 10 }}>
        <div className="faint" style={{ fontSize: 11, marginBottom: 2 }}>TICKERS</div>
        <input value={symbols} onChange={(e) => setSymbols(e.target.value)} style={{ width: "100%" }} placeholder="NVDA, AAPL" />
      </label>
      {err && <div className="msg" style={{ color: "var(--red)" }}>{err}</div>}
      <button onClick={start} disabled={busy || !date || !symbols.trim()}>
        {busy ? "starting…" : "Start replay"}
      </button>
    </div>
  );
}
