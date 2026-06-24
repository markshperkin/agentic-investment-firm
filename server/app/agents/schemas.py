from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["BULLISH", "BEARISH", "NEUTRAL", "INSUFFICIENT_EVIDENCE"]
Strategy = Literal["BASELINE", "DECOMPOSE", "STEPBACK", "HYDE", "FILTER_FIX"]
FailureKind = Literal["NONE", "NO_HITS", "WRONG_ENTITY", "STALE", "TOO_GENERIC", "OFF_TOPIC"]


class QueryPlan(BaseModel):
    queries: list[str] = Field(min_length=1)
    strategy: Strategy = "BASELINE"
    date_window_days: int | None = None


class RelevanceGrade(BaseModel):
    relevant: bool
    coverage: float = Field(ge=0.0, le=1.0)
    missing: str = ""
    failure_kind: FailureKind = "NONE"
    fix_hint: str = ""


class Citation(BaseModel):
    chunk_id: str
    source: str = ""
    published_date: str = ""
    quote: str = ""


class KeyPoint(BaseModel):
    text: str
    citation: Citation


class ResearchView(BaseModel):
    ticker: str
    stance: Stance
    confidence: float = Field(ge=0.0, le=1.0)
    key_points: list[KeyPoint] = Field(default_factory=list)


class ThesisCard(BaseModel):
    headline: str
    why_now: str
    expected_edge: str
    risks: str
    confidence: float = Field(ge=0.0, le=1.0)
    key_evidence: list[Citation] = Field(default_factory=list)


class TradeProposal(BaseModel):
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    est_notional: float = Field(ge=0.0)
    thesis_card: ThesisCard


class PMDecision(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    thesis_card: ThesisCard


class NoTrade(BaseModel):
    reason: str


class RiskNarrative(BaseModel):
    decision: Literal["REQUIRE_HUMAN", "REJECT"]
    reasoning: str
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
