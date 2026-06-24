from functools import lru_cache

from app.config import get_settings
from app.rag.edgar import EdgarSource
from app.rag.embeddings import Embedder, FakeEmbedder, VoyageEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore, VectorStore


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.llm_mode == "cassette" or not s.voyage_api_key:
        return FakeEmbedder()
    return VoyageEmbedder(api_key=s.voyage_api_key)


@lru_cache
def get_store() -> VectorStore:
    # Chroma for live/persistent; in-memory fallback keeps things working offline.
    try:
        from app.rag.vector_store import ChromaVectorStore

        return ChromaVectorStore()
    except Exception:
        return InMemoryVectorStore()


@lru_cache
def get_retriever() -> Retriever:
    return Retriever(get_embedder(), get_store())


def get_corpus_ingester() -> CorpusIngester:
    return CorpusIngester(EdgarSource(), get_embedder(), get_store())
