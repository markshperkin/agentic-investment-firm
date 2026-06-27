import { useEffect, useState } from "react";
import { getPortfolio, PortfolioState } from "../api";
import { money } from "../format";

export default function PortfolioPanel() {
  const [state, setState] = useState<PortfolioState | null>(null);

  useEffect(() => {
    getPortfolio().then(setState);
    const t = setInterval(() => getPortfolio().then(setState), 3000);
    return () => clearInterval(t);
  }, []);

  if (!state) return <div className="empty">Loading portfolio…</div>;

  return (
    <div className="main-narrow">
      <div className="faint" style={{ marginBottom: 12, fontSize: 12 }}>
        Live book (current account state).
      </div>
      <div className="stats-row">
        <div className="stat"><div className="k">Cash</div><div className="v">{money(state.cash)}</div></div>
        <div className="stat"><div className="k">Equity (at cost)</div><div className="v">{money(state.equity_at_cost)}</div></div>
        <div className="stat"><div className="k">Positions</div><div className="v">{state.holdings.length}</div></div>
      </div>
      <table className="tbl">
        <thead>
          <tr><th>Ticker</th><th>Qty</th><th>Avg cost</th><th>Realized P&L</th></tr>
        </thead>
        <tbody>
          {state.holdings.map((h) => (
            <tr key={h.ticker}>
              <td>{h.ticker}</td>
              <td>{h.quantity}</td>
              <td>{money(h.avg_cost_basis, 2)}</td>
              <td className={h.realized_pnl >= 0 ? "pos" : "neg"}>{money(h.realized_pnl, 2)}</td>
            </tr>
          ))}
          {!state.holdings.length && (
            <tr><td colSpan={4} className="faint">No open positions.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
