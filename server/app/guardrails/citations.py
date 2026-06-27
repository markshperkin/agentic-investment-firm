import re

from app.agents.schemas import ResearchView
from app.rag.retriever import RetrievedChunk

_NUM = re.compile(r"\d[\d,]*\.?\d*")
_LABEL = re.compile(r"\[[^\]]*\]")  # model-inserted quote labels, e.g. "[Q1 FY2027]"


def _numbers(text: str) -> set[str]:
    return {m.group().replace(",", "") for m in _NUM.finditer(text)}


def _quoted_numbers(quote: str) -> set[str]:
    # Drop bracketed labels the model adds to clarify table columns before reading
    # figures, so its annotations (e.g. the 2027 in "[Q1 FY2027]") aren't mistaken
    # for quoted source numbers.
    return _numbers(_LABEL.sub(" ", quote))


def verify_view(view: ResearchView, chunks: list[RetrievedChunk]) -> ResearchView:
    """Ground each key point against its cited chunk: the citation must point to a
    real retrieved chunk, and the figures in its quote must actually appear there.

    We check the quote's numbers, not the point's prose — the prose may paraphrase or
    derive figures (e.g. a computed "64% higher") that are valid but not printed
    verbatim. A non-neutral stance left with no grounded points collapses to
    INSUFFICIENT_EVIDENCE."""
    by_id = {c.chunk_id: c.text for c in chunks}
    kept = []
    for kp in view.key_points:
        cid = kp.citation.chunk_id
        if cid not in by_id:
            continue  # fabricated citation
        if not _quoted_numbers(kp.citation.quote) <= _numbers(by_id[cid]):
            continue  # a quoted figure is absent from the source
        kept.append(kp)

    view.key_points = kept
    if view.stance in ("BULLISH", "BEARISH") and not kept:
        view.stance = "INSUFFICIENT_EVIDENCE"
        view.confidence = 0.0
    return view
