from app.db import SessionLocal
from app.models.corpus import Chunk, Document
from app.rag.factory import get_embedder, get_store


class CorpusCorrupted(Exception):
    """No corpus rows in SQL for the requested tickers — the run cannot proceed and
    the dataset must be re-ingested."""


def ensure_corpus_ready(tickers: list[str]) -> dict:
    """Preflight data-integrity gate, run before a replay starts.

    * No corpus in SQL for these tickers -> raise CorpusCorrupted (stop the run).
    * Corpus present in SQL but vectors missing from the store -> embed the gap and
      backfill the vector store, so retrieval can never silently return nothing.
    """
    with SessionLocal() as s:
        sql_ids = {c.id for c in s.query(Chunk).filter(Chunk.ticker.in_(tickers)).all()}
    if not sql_ids:
        raise CorpusCorrupted(
            f"No corpus in SQL for {', '.join(tickers)} — data is corrupted. "
            "Re-ingest the dataset before running."
        )

    store = get_store()
    missing = sql_ids - store.ids()
    if not missing:
        return {"status": "ok", "chunks": len(sql_ids)}

    # SQL has the corpus but the vector store is missing some/all of it — embed and fill.
    with SessionLocal() as s:
        docs = {d.id: d for d in s.query(Document).all()}
        to_fill = s.query(Chunk).filter(Chunk.id.in_(missing)).all()
        ids = [c.id for c in to_fill]
        texts = [c.text for c in to_fill]
        metas = [
            {
                "chunk_id": c.id, "ticker": c.ticker, "published_ts": c.published_ts,
                "published_date": docs[c.document_id].published_date if c.document_id in docs else "",
                "form_type": docs[c.document_id].form_type if c.document_id in docs else "",
                "source": docs[c.document_id].source_url if c.document_id in docs else "",
            }
            for c in to_fill
        ]
    vecs = get_embedder().embed(texts)
    store.add(ids, vecs, metas)
    return {"status": "backfilled", "embedded": len(ids)}
