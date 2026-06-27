import re

from app.llm.base import ProviderResult

_TICKER = re.compile(r"Ticker:\s*([A-Z.\-]+)")
_CHUNK = re.compile(r"\[([^\]]+)\]")


def _ticker(prompt: str) -> str:
    m = _TICKER.search(prompt)
    return m.group(1) if m else "NVDA"


def _first_chunk_id(prompt: str) -> str:
    m = _CHUNK.search(prompt)
    return m.group(1) if m else "missing"


class EvalProvider:
    """Deterministic stand-in for a live model, keyed off the response schema rather
    than a recorded sequence — so a full replay is reproducible no matter how many
    calls each path makes. Cites the first excerpt it is shown and states no numbers,
    so the citation guardrail passes honestly. Zero network, zero real tokens."""

    def __init__(self, *, relevant: bool = True, stance: str = "BULLISH",
                 confidence: float = 0.8, pm_action: str = "BUY",
                 eod_action: str = "HOLD", cite: str | None = None):
        self.relevant = relevant
        self.stance = stance
        self.confidence = confidence
        self.pm_action = pm_action
        self.eod_action = eod_action
        self.cite = cite

    def complete(self, model: str, system: str, prompt: str, schema) -> ProviderResult:
        name = schema.__name__
        data = self._data(name, prompt)
        return ProviderResult(data=data, prompt_tokens=10, completion_tokens=10)

    def _data(self, name: str, prompt: str) -> dict:
        if name == "QueryPlan":
            return {"queries": [f"{_ticker(prompt)} fundamentals"], "strategy": "BASELINE"}
        if name == "RelevanceGrade":
            return {"relevant": self.relevant, "coverage": 0.9 if self.relevant else 0.1,
                    "failure_kind": "NONE" if self.relevant else "OFF_TOPIC",
                    "fix_hint": "" if self.relevant else "narrow the query"}
        if name == "ResearchView":
            cite = self.cite or _first_chunk_id(prompt)
            return {"ticker": _ticker(prompt), "stance": self.stance, "confidence": self.confidence,
                    "key_points": [{"text": "Operating momentum looks positive.",
                                    "citation": {"chunk_id": cite}}]}
        if name == "PMDecision":
            return {"action": self.pm_action,
                    "thesis_card": {"headline": "thesis", "why_now": "catalyst",
                                    "expected_edge": "edge", "risks": "macro",
                                    "confidence": self.confidence, "key_evidence": []}}
        if name == "RiskNarrative":
            return {"decision": "REQUIRE_HUMAN", "reasoning": "sizeable entry", "severity": "MEDIUM"}
        if name == "EodDecision":
            return {"action": self.eod_action, "reasoning": "thesis intact", "gap_risk": "LOW"}
        if name == "ReportSummary":
            return {"headline": "EOD", "summary": "summary", "risk_note": "none"}
        raise ValueError(f"EvalProvider has no canned response for schema {name}")
