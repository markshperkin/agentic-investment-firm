import re

from app.agents.schemas import ResearchView
from app.rag.retriever import RetrievedChunk

_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _numbers(text: str) -> set[str]:
    return {m.group().replace(",", "") for m in _NUM.finditer(text)}


def verify_view(view: ResearchView, chunks: list[RetrievedChunk]) -> ResearchView:
    """Strip any key point whose citation is fabricated, whose quote is not in the
    cited chunk, or that states a number absent from the cited chunk. A non-neutral
    stance left with no grounded points collapses to INSUFFICIENT_EVIDENCE."""
    by_id = {c.chunk_id: c.text for c in chunks}
    kept = []
    for kp in view.key_points:
        cid = kp.citation.chunk_id
        if cid not in by_id:
            continue  # fabricated citation
        chunk_text = by_id[cid]
        quote = kp.citation.quote.strip()
        if quote and quote.lower() not in chunk_text.lower():
            continue  # quote not supported
        if not _numbers(kp.text) <= _numbers(chunk_text):
            continue  # a stated number is absent from the source
        kept.append(kp)

    view.key_points = kept
    if view.stance in ("BULLISH", "BEARISH") and not kept:
        view.stance = "INSUFFICIENT_EVIDENCE"
        view.confidence = 0.0
    return view
