import json

from app.agents.schemas import ReportSummary
from app.llm.router import LLMRouter
from app.obs.spans import span

SYSTEM = (
    "You are the firm's reporting analyst. Write a brief, factual end-of-day summary "
    "for the operator using ONLY the figures provided. Do not invent or recompute any "
    "number. State performance vs the benchmark, what drove it, and any open risk."
)


def deterministic_summary(report: dict) -> ReportSummary:
    """No-LLM fallback so the report channel always works offline. Pure templating
    over store-derived numbers."""
    m = report["metrics"]
    bench = m["benchmark"]
    pr = m["portfolio_return"]
    br = m["benchmark_return"]
    vs = f"{(m['alpha'] or 0) * 100:+.2f}% vs {bench}" if br is not None else f"{bench} unavailable"
    return ReportSummary(
        headline=f"{report.get('replay_date', 'run')}: equity ${m['equity']:,.0f} "
                 f"({pr * 100:+.2f}%)",
        summary=f"Closed with ${m['cash']:,.0f} cash and ${m['holdings_value']:,.0f} in {len(report['holdings'])} "
                f"position(s) across {m['n_trades']} filled trade(s). Day return {pr * 100:+.2f}%, {vs}.",
        risk_note=f"{report['process']['risk_engine_rejects']} risk-engine rejects, "
                  f"{report['process']['refusals']} refusals, "
                  f"{report['process']['injection_quarantines']} injection quarantines.",
    )


class ReportingAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def narrate(self, report: dict) -> ReportSummary:
        with span("AGENT", "reporting", agent="reporting") as h:
            payload = {"metrics": report["metrics"], "process": report["process"],
                       "holdings": report["holdings"], "n_decisions": len(report["decisions"])}
            try:
                out = self.router.complete(
                    "reporting", system=SYSTEM,
                    prompt="Figures (authoritative):\n" + json.dumps(payload, default=str),
                    schema=ReportSummary,
                ).value
            except Exception:  # noqa: BLE001  no cassette / no key -> deterministic fallback
                out = deterministic_summary(report)
            h.set_output(out.model_dump())
            return out
