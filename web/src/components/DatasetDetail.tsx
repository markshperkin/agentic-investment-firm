import { useEffect, useState } from "react";
import { DatasetDay, getDatasets, TickerStats } from "../api";

export default function DatasetDetail({ date }: { date: string }) {
  const [day, setDay] = useState<DatasetDay | null>(null);

  useEffect(() => {
    setDay(null);
    getDatasets().then((days) => setDay(days.find((d) => d.replay_date === date) ?? null));
  }, [date]);

  if (!day) return <div className="empty">Loading dataset…</div>;

  return (
    <div>
      <div className="detail-head">
        <h2 className="mono">{day.replay_date}</h2>
        <span className="badge">{day.tickers.length} ticker{day.tickers.length === 1 ? "" : "s"}</span>
      </div>
      <table className="tbl">
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Filings (7d / day / total)</th>
            <th>Chunks (7d / day / total)</th>
            <th>Candles (day / total)</th>
            <th>Interval</th>
            <th>Corpus</th>
            <th>Checks</th>
          </tr>
        </thead>
        <tbody>
          {day.stats.map((s) => <StatRow key={s.ticker} s={s} />)}
        </tbody>
      </table>
    </div>
  );
}

function StatRow({ s }: { s: TickerStats }) {
  const ok = s.warnings.length === 0;
  return (
    <tr>
      <td>{s.ticker}</td>
      <td>{s.filings.prior_7d} / <strong>{s.filings.current_day}</strong> / {s.filings.total}</td>
      <td>{s.chunks.prior_7d} / {s.chunks.current_day} / {s.chunks.total}</td>
      <td>{s.prices.n_bars_current_day ?? 0} / {s.prices.n_bars ?? 0}</td>
      <td>{s.prices.interval ?? "—"}</td>
      <td>{s.corpus_status}</td>
      <td>
        {ok ? <span className="pos">✓ ok</span>
          : <span className="neg" title={s.warnings.join("\n")}>⚠ {s.warnings.length}</span>}
      </td>
    </tr>
  );
}
