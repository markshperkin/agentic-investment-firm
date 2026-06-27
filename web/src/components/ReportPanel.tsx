import { useEffect, useState } from "react";
import { exportUrl, reportXlsxUrl } from "../api";
import { cachedReport, prefetchReport } from "../reports";
import { money, pct } from "../format";

export default function ReportPanel({ runId }: { runId: string }) {
  const [rep, setRep] = useState<any | null>(cachedReport(runId) ?? null);

  useEffect(() => {
    setRep(cachedReport(runId) ?? null);
    prefetchReport(runId).then(setRep);
  }, [runId]);

  if (!rep) return <div className="empty">Loading report…</div>;
  const m = rep.metrics ?? {};

  return (
    <div className="main-narrow">
      <div className="toolbar">
        <a href={reportXlsxUrl(runId)}>Download .xlsx</a>
        <a href={exportUrl(runId)}>Export trace (JSONL)</a>
      </div>

      {rep.narrative && (
        <div className="card">
          <div style={{ fontSize: 16, fontWeight: 600 }}>{rep.narrative.headline}</div>
          <p style={{ margin: "6px 0" }}>{rep.narrative.summary}</p>
          <p style={{ color: "var(--yellow)", margin: 0 }}>{rep.narrative.risk_note}</p>
        </div>
      )}

      <div className="stats-row">
        <div className="stat"><div className="k">Equity</div><div className="v">{money(m.equity)}</div></div>
        <div className="stat"><div className="k">Cash</div><div className="v">{money(m.cash)}</div></div>
        <div className="stat"><div className="k">Return</div><div className="v">{pct(m.portfolio_return)}</div></div>
        <div className="stat"><div className="k">{m.benchmark ?? "Bench"}</div><div className="v">{pct(m.benchmark_return)}</div></div>
        <div className="stat"><div className="k">Alpha</div><div className="v">{pct(m.alpha)}</div></div>
        <div className="stat"><div className="k">Trades</div><div className="v">{m.n_trades ?? 0}</div></div>
      </div>

      <h4 className="section">Holdings</h4>
      <table className="tbl">
        <thead><tr><th>Ticker</th><th>Qty</th><th>Avg cost</th><th>Mark</th><th>Unrealized</th></tr></thead>
        <tbody>
          {(rep.holdings ?? []).map((h: any) => (
            <tr key={h.ticker}>
              <td>{h.ticker}</td><td>{h.quantity}</td>
              <td>{money(h.avg_cost_basis, 2)}</td><td>{money(h.mark, 2)}</td>
              <td className={h.unrealized_pnl >= 0 ? "pos" : "neg"}>{money(h.unrealized_pnl, 2)}</td>
            </tr>
          ))}
          {!(rep.holdings ?? []).length && <tr><td colSpan={5} className="faint">No holdings.</td></tr>}
        </tbody>
      </table>

      <h4 className="section">Decision log</h4>
      <table className="tbl">
        <thead><tr><th>Tick</th><th>Ticker</th><th>Path</th><th>Action</th><th>Shares</th><th>Stance</th><th>Conf</th><th>Thesis</th></tr></thead>
        <tbody>
          {(rep.decisions ?? []).map((d: any, i: number) => (
            <tr key={i}>
              <td>t{d.tick_seq}</td><td>{d.ticker}</td><td>{d.path}</td>
              <td>{d.action ?? "—"}</td><td className="mono">{d.shares_held ?? 0}</td>
              <td>{d.stance ?? "—"}</td><td>{d.confidence ?? "—"}</td>
              <td style={{ whiteSpace: "normal" }}>{d.thesis ?? ""}</td>
            </tr>
          ))}
          {!(rep.decisions ?? []).length && <tr><td colSpan={8} className="faint">No decisions.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
