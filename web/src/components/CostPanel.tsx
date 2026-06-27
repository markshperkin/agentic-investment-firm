import { useEffect, useState } from "react";
import { getCost } from "../api";

export default function CostPanel({ runId }: { runId: string }) {
  const [cost, setCost] = useState<any | null>(null);

  useEffect(() => {
    setCost(null);
    getCost(runId).then(setCost);
  }, [runId]);

  const num = (n: number) => (n ?? 0).toLocaleString();
  const usd = (n: number) => `$${(n ?? 0).toFixed(4)}`;

  if (!cost) return <div className="empty">Loading cost…</div>;

  return (
    <div className="main-narrow">
      <h4 className="section">Totals</h4>
      <div className="stats-row">
        <div className="stat"><div className="k">Calls</div><div className="v">{cost.total.calls}</div></div>
        <div className="stat"><div className="k">Input tokens</div><div className="v">{num(cost.total.input_tokens)}</div></div>
        <div className="stat"><div className="k">Output tokens</div><div className="v">{num(cost.total.output_tokens)}</div></div>
        <div className="stat"><div className="k">Cost</div><div className="v">{usd(cost.total.cost_usd)}</div></div>
      </div>

      <h4 className="section">By agent</h4>
      <table className="tbl">
        <thead><tr><th>Agent</th><th>Calls</th><th>Input tok</th><th>Output tok</th><th>Cost</th></tr></thead>
        <tbody>
          {Object.entries(cost.by_agent).map(([agent, v]: any) => (
            <tr key={agent}>
              <td>{agent}</td><td>{v.calls}</td>
              <td>{num(v.input_tokens)}</td><td>{num(v.output_tokens)}</td><td>{usd(v.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4 className="section">By model</h4>
      <table className="tbl">
        <thead><tr><th>Model</th><th>Calls</th><th>Input tok</th><th>Output tok</th><th>Cost</th><th>Rate /1M (in / out)</th></tr></thead>
        <tbody>
          {Object.entries(cost.by_model).map(([model, v]: any) => {
            const r = cost.rates?.[model];
            return (
              <tr key={model}>
                <td>{model}</td><td>{v.calls}</td>
                <td>{num(v.input_tokens)}</td><td>{num(v.output_tokens)}</td><td>{usd(v.cost_usd)}</td>
                <td>{r ? `$${r.input_per_m} / $${r.output_per_m}` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
        Cost = input × in-rate + output × out-rate (per 1M tokens). Output tokens are billed higher.
      </div>
    </div>
  );
}
