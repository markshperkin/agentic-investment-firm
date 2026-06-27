import { useState } from "react";
import { Approval, decideApproval } from "../api";

export default function HitlActions({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [qty, setQty] = useState(approval.quantity);
  const [err, setErr] = useState<string | null>(null);

  if (approval.status !== "PENDING") {
    const ok = approval.status === "APPROVED";
    return (
      <div className={`hitl-outcome ${ok ? "ok" : "rej"}`}>
        {ok ? "✓ Approved" : "✕ Rejected"}
        {approval.approver ? ` by ${approval.approver}` : ""}
        {approval.decision === "edit" && approval.edited_quantity ? ` · qty → ${approval.edited_quantity}` : ""}
        {approval.reject_reason ? ` · ${approval.reject_reason}` : ""}
      </div>
    );
  }

  const act = async (decision: "approve" | "edit" | "reject") => {
    setBusy(true);
    setErr(null);
    try {
      await decideApproval(approval.id, decision, decision === "edit" ? qty : undefined);
      onDecided();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="hitl-bar">
      <span className="hitl-need">⚠ Awaiting your decision</span>
      <div className="hitl-actions">
        <button className="btn-accept" disabled={busy} onClick={() => act("approve")}>Accept</button>
        <button className="btn-reject" disabled={busy} onClick={() => act("reject")}>Reject</button>
        {adjusting ? (
          <>
            <input
              className="adjust-input mono"
              type="number"
              value={qty}
              min={1}
              onChange={(e) => setQty(parseInt(e.target.value, 10) || 0)}
            />
            <button disabled={busy || qty <= 0} onClick={() => act("edit")}>Confirm</button>
            <button disabled={busy} onClick={() => setAdjusting(false)}>Cancel</button>
          </>
        ) : (
          <button disabled={busy} onClick={() => setAdjusting(true)}>Adjust qty</button>
        )}
      </div>
      {err && <div className="msg" style={{ color: "var(--red)" }}>{err}</div>}
    </div>
  );
}
