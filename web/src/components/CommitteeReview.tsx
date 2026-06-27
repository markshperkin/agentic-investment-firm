import { Approval } from "../api";
import { money, pct } from "../format";
import RichText from "./RichText";

export default function CommitteeReview({ approval }: { approval: Approval }) {
  const t = approval.thesis_card;
  const sev = approval.risk_severity;
  return (
    <div className="committee">
      <div className="hitl-order">
        <span className={`hitl-side ${approval.side === "BUY" ? "buy" : "sell"}`}>{approval.side}</span>
        <span className="hitl-qty">{approval.quantity} {approval.ticker}</span>
        <span className="dim">{money(approval.est_notional)} @ {money(approval.reference_price, 2)}</span>
      </div>
      <div className="hitl-chips">
        {t?.confidence != null && <span className="chip">confidence {Math.round(t.confidence * 100)}%</span>}
        <span className="chip chip-stop">stop {pct(approval.stop_loss_pct)}</span>
        <span className="chip chip-target">target {pct(approval.take_profit_pct)}</span>
      </div>

      {t && (
        <div className="hitl-section">
          <div className="hitl-from">Portfolio Manager</div>
          {t.headline && <div className="hitl-headline">{t.headline}</div>}
          {t.why_now && <Field label="Why now" value={t.why_now} />}
          {t.expected_edge && <Field label="Expected edge" value={t.expected_edge} />}
          {t.risks && <Field label="Risks" value={t.risks} />}
        </div>
      )}

      {approval.risk_reasoning && (
        <div className="hitl-section">
          <div className="hitl-from">
            Risk Narrator
            {sev && <span className={`sev sev-${sev.toLowerCase()}`}>{sev}</span>}
          </div>
          <RichText text={approval.risk_reasoning} />
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="hitl-field">
      <div className="hitl-field-key">{label}</div>
      <div className="hitl-field-val">{value}</div>
    </div>
  );
}
