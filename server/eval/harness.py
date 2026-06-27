import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.firm.hitl import resolve_approval
from app.firm.runner import run_replay
from app.llm.router import LLMRouter
from app.models.approval import ApprovalRequest
from app.reports.builder import build_report

from eval.provider import EvalProvider
from eval.scenarios import GOLDEN, REDTEAM, ScenarioResult, _clean, _retriever

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "eval-report.md"
_DATE = "2024-05-23"


def _full_run() -> dict:
    """End-to-end replay with deterministic agents: one grounded entry, auto-approved
    by a simulated operator, marked to the close. Yields the return metrics (P&L vs
    SPY) and the process metrics off the same trace."""
    _clean()
    tmp = Path(tempfile.mkdtemp())
    price_feed.PRICES_DIR = tmp

    def fetch(t, s, e, i):
        close = 110.0 if t == "NVDA" else 100.0  # NVDA +10%, SPY flat
        return pd.DataFrame({"ts": [datetime(2024, 5, 23, 9, 30), datetime(2024, 5, 23, 15, 30)],
                             "open": [100, close], "high": [close + 2, close + 2],
                             "low": [98, close - 2], "close": [100.0, close], "volume": [1000, 1100]})
    PriceIngester(fetch=fetch, prices_dir=tmp).ingest(_DATE, ["NVDA"])

    retriever = _retriever(["Nvidia data center revenue rose to record levels this quarter."])
    router = LLMRouter(provider=EvalProvider())
    # Non-blocking: the run queues approvals and continues; the simulated operator
    # below approves them, then we build the report.
    run_id = run_replay(_DATE, ["NVDA"], retriever=retriever, router=router,
                        block_on_approval=False)

    # simulated operator approves everything the firm escalated
    from app.db import SessionLocal
    with SessionLocal() as s:
        pending = [a.id for a in s.query(ApprovalRequest).filter_by(status="PENDING").all()]
    for appr_id in pending:
        resolve_approval(appr_id, decision="approve", approver="eval")

    return {"run_id": run_id, "report": build_report(run_id), "approved": len(pending)}


def run_eval() -> dict:
    results: list[ScenarioResult] = [f() for f in GOLDEN] + [f() for f in REDTEAM]
    golden = [r for r in results if r.category == "golden"]
    redteam = [r for r in results if r.category == "redteam"]

    full = _full_run()
    rep = full["report"]

    metrics = {
        "golden_pass_rate": round(sum(r.passed for r in golden) / len(golden), 3),
        "redteam_block_rate": round(sum(r.passed for r in redteam) / len(redteam), 3),
        "refusal_correct": next(r.passed for r in golden if r.name == "insufficient_evidence"),
        "grounding_correct": all(r.passed for r in golden
                                 if r.name in ("grounded_entry", "fabricated_citation")),
        "return_metrics": rep["metrics"],
        "process_metrics": rep["process"],
    }
    write_report(results, metrics, full)
    return {"results": results, "metrics": metrics, "full": full}


def write_report(results, metrics, full) -> None:
    rm, pm = metrics["return_metrics"], metrics["process_metrics"]

    def pct(x):
        return "n/a" if x is None else f"{x * 100:+.2f}%"

    lines = [
        "# Eval Report",
        "",
        "Deterministic, offline eval — no network, no real tokens. Regenerate with "
        "`cd server && python -m eval.harness` or via the `test_eval` suite (CI).",
        "",
        "## Return metrics (sample replay)",
        "",
        f"- Replay day: `{rm.get('benchmark') and full['report']['replay_date']}`",
        f"- Portfolio return: **{pct(rm['portfolio_return'])}**",
        f"- {rm['benchmark']} return: {pct(rm['benchmark_return'])}",
        f"- Alpha: **{pct(rm['alpha'])}**",
        f"- Filled trades: {rm['n_trades']} · Approvals auto-approved: {full['approved']}",
        "",
        "## Process metrics",
        "",
        f"- Groundedness (cited views passing the citation check): "
        f"{pm['groundedness'] if pm['groundedness'] is not None else 'n/a'}",
        f"- Refusals: {pm['refusals']} · Risk-engine rejects: {pm['risk_engine_rejects']} · "
        f"Injection quarantines: {pm['injection_quarantines']}",
        f"- Total cost (stubbed tokens): ${pm['total_cost_usd']} over {pm['total_tokens']} tokens",
        "",
        "## Scenario results",
        "",
        "| Scenario | Category | Result |",
        "| --- | --- | --- |",
    ]
    for r in results:
        lines.append(f"| {r.name} | {r.category} | {'PASS' if r.passed else 'FAIL'} |")
    lines += [
        "",
        "## Aggregate",
        "",
        f"- Golden pass rate: **{metrics['golden_pass_rate']}**",
        f"- Red-team block rate: **{metrics['redteam_block_rate']}**",
        f"- Refusal correct: {metrics['refusal_correct']} · Grounding correct: {metrics['grounding_correct']}",
        "",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    from app.db import init_db

    init_db()
    out = run_eval()
    print(f"golden_pass_rate={out['metrics']['golden_pass_rate']} "
          f"redteam_block_rate={out['metrics']['redteam_block_rate']}")
    print(f"report written to {REPORT_PATH}")
