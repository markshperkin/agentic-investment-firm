import { useEffect, useState } from "react";
import { DatasetDay, deleteAllDatasets, getDatasets, ingestDataset, ingestDemoDataset } from "../api";

export default function DatasetList({
  selectedDate,
  onSelect,
  onChanged,
}: {
  selectedDate: string | null;
  onSelect: (date: string) => void;
  onChanged: () => void;
}) {
  const [days, setDays] = useState<DatasetDay[]>([]);
  const [date, setDate] = useState("2024-05-23");
  const [symbols, setSymbols] = useState("NVDA");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = () => getDatasets().then(setDays);
  useEffect(() => {
    refresh();
  }, []);

  const onIngest = async () => {
    setBusy("ingest");
    setMsg(null);
    try {
      const tickers = symbols.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
      await ingestDataset(date, tickers);
      setMsg(`Ingested ${tickers.join(", ")} for ${date}.`);
      await refresh();
      onChanged();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(null);
    }
  };

  const onDemo = async () => {
    setBusy("demo");
    setMsg(null);
    try {
      const res = await ingestDemoDataset();
      setMsg(`Demo dataset ready for ${res.date} — run it to exercise every path.`);
      await refresh();
      onChanged();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(null);
    }
  };

  const onDeleteAll = async () => {
    if (!confirm("Delete ALL datasets — filings, vectors and price candles — for every day? This cannot be undone.")) return;
    setBusy("delete");
    setMsg(null);
    try {
      await deleteAllDatasets();
      setMsg("All datasets deleted.");
      await refresh();
      onChanged();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="panel-head">
        <h3>Datasets</h3>
        {days.length > 0 && (
          <button className="right btn-reject" onClick={onDeleteAll} disabled={busy === "delete"}>
            {busy === "delete" ? "…" : "Delete all"}
          </button>
        )}
      </div>

      <div style={{ padding: 12, borderBottom: "1px solid var(--border-soft)" }}>
        <div className="faint" style={{ fontSize: 11, marginBottom: 4 }}>INGEST A DAY</div>
        <input value={date} onChange={(e) => setDate(e.target.value)} style={{ width: "100%", marginBottom: 6 }} placeholder="2024-05-23" />
        <input value={symbols} onChange={(e) => setSymbols(e.target.value)} style={{ width: "100%", marginBottom: 8 }} placeholder="NVDA, AAPL" />
        <button onClick={onIngest} disabled={busy !== null}>{busy === "ingest" ? "ingesting…" : "Ingest"}</button>
        <button onClick={onDemo} disabled={busy !== null} style={{ marginLeft: 8 }} title="Scripted NVDA day (2026-05-29) that fires every dispatch path in one run">
          {busy === "demo" ? "loading…" : "Load demo dataset"}
        </button>
        {msg && <div className="msg">{msg}</div>}
      </div>

      <div className="list">
        {!days.length && <div className="empty">No datasets yet.<br />Ingest a day above.</div>}
        {days.map((d) => (
          <div
            key={d.replay_date}
            className={"list-row" + (d.replay_date === selectedDate ? " selected" : "")}
            onClick={() => onSelect(d.replay_date)}
          >
            <div>
              <div className="title">{d.replay_date}</div>
              <div className="sub">{d.tickers.length} ticker{d.tickers.length === 1 ? "" : "s"} · {d.tickers.join(", ")}</div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
