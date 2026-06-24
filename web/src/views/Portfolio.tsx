import { useEffect, useState } from "react";
import { getPortfolio, PortfolioState } from "../api";

export default function Portfolio() {
  const [state, setState] = useState<PortfolioState | null>(null);

  useEffect(() => {
    getPortfolio().then(setState);
    const t = setInterval(() => getPortfolio().then(setState), 3000);
    return () => clearInterval(t);
  }, []);

  if (!state) return <p>Loading portfolio…</p>;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", fontFamily: "system-ui" }}>
      <h2>Portfolio</h2>
      <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
        <Stat label="Cash" value={`$${state.cash.toLocaleString()}`} />
        <Stat label="Equity (at cost)" value={`$${state.equity_at_cost.toLocaleString()}`} />
        <Stat label="Positions" value={String(state.holdings.length)} />
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
            <th>Ticker</th>
            <th>Qty</th>
            <th>Avg cost</th>
            <th>Realized P&L</th>
          </tr>
        </thead>
        <tbody>
          {state.holdings.map((h) => (
            <tr key={h.ticker} style={{ borderBottom: "1px solid #eee" }}>
              <td>{h.ticker}</td>
              <td>{h.quantity}</td>
              <td>${h.avg_cost_basis.toFixed(2)}</td>
              <td style={{ color: h.realized_pnl >= 0 ? "#2a7" : "#c00" }}>
                ${h.realized_pnl.toFixed(2)}
              </td>
            </tr>
          ))}
          {state.holdings.length === 0 && (
            <tr>
              <td colSpan={4} style={{ color: "#aaa", padding: "8px 0" }}>
                No open positions.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ color: "#888", fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
    </div>
  );
}
