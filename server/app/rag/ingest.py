import hashlib
import uuid
from datetime import datetime, timedelta

from app.data.catalog import record_asset
from app.db import SessionLocal
from app.models.corpus import Chunk, Document
from app.rag.chunker import chunk_text, estimate_tokens
from app.rag.edgar import FilingSource
from app.rag.embeddings import Embedder
from app.rag.vector_store import VectorStore


class CorpusIngester:
    def __init__(self, source: FilingSource, embedder: Embedder, store: VectorStore):
        self.source = source
        self.embedder = embedder
        self.store = store

    def ingest(self, replay_date: str, tickers: list[str], lookback_days: int = 120) -> dict[str, str]:
        day = datetime.fromisoformat(replay_date)
        since = day - timedelta(days=lookback_days)
        until = day.replace(hour=23, minute=59, second=59)
        results: dict[str, str] = {}
        for ticker in tickers:
            try:
                n = self._ingest_ticker(ticker, since, until)
                record_asset(replay_date, ticker, "CORPUS", "READY", {"n_docs": n})
                results[ticker] = "READY"
            except Exception as exc:  # noqa: BLE001
                record_asset(replay_date, ticker, "CORPUS", "FAILED", {"reason": str(exc)})
                results[ticker] = "FAILED"
        return results

    def _ingest_ticker(self, ticker: str, since: datetime, until: datetime) -> int:
        filings = self.source.fetch(ticker, since, until)
        n_docs = 0
        for f in filings:
            content_hash = hashlib.sha256(f.text.encode()).hexdigest()
            with SessionLocal() as s:
                if s.query(Document).filter_by(content_hash=content_hash).first():
                    continue
                doc_id = uuid.uuid4().hex
                published_ts = f.published_at.timestamp()
                s.add(Document(
                    id=doc_id, ticker=ticker, form_type=f.form_type, source_url=f.source_url,
                    published_date=f.published_at.isoformat(), published_ts=published_ts,
                    content_hash=content_hash,
                ))
                pieces = chunk_text(f.text)
                ids, vecs, metas, rows = [], [], [], []
                for i, piece in enumerate(pieces):
                    cid = f"{doc_id}:{i}"
                    ids.append(cid)
                    metas.append({"chunk_id": cid, "ticker": ticker, "published_ts": published_ts,
                                  "published_date": f.published_at.isoformat(), "form_type": f.form_type,
                                  "source": f.source_url})
                    rows.append(Chunk(id=cid, document_id=doc_id, ticker=ticker, ordinal=i,
                                      text=piece, token_count=estimate_tokens(piece),
                                      published_ts=published_ts))
                if pieces:
                    vecs = self.embedder.embed(pieces)
                    self.store.add(ids, vecs, metas)
                    s.add_all(rows)
                s.commit()
                n_docs += 1
        return n_docs
