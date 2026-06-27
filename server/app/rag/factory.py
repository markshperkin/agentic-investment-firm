from functools import lru_cache

from app.config import get_settings
from app.rag.edgar import EdgarSource
from app.rag.embeddings import Embedder, FakeEmbedder, VoyageEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore, VectorStore


@lru_cache
def get_embedder() -> Embedder:
    # Deterministic fake offline (cassette); real Voyage in live mode — and live mode
    # fails loudly if the key is missing rather than silently degrading to the fake.
    s = get_settings()
    if s.llm_mode == "cassette":
        return FakeEmbedder()
    if not s.voyage_api_key:
        raise RuntimeError("LLM_MODE=live requires VOYAGE_API_KEY for embeddings")
    return VoyageEmbedder(api_key=s.voyage_api_key)


@lru_cache
def get_store() -> VectorStore:
    # In-memory offline (cassette); persistent Chroma in live mode. A missing/broken
    # Chroma in live mode is a hard error, not a silent in-memory fallback.
    s = get_settings()
    if s.llm_mode == "cassette":
        return InMemoryVectorStore()
    from app.rag.vector_store import ChromaVectorStore

    return ChromaVectorStore()


@lru_cache
def get_retriever() -> Retriever:
    return Retriever(get_embedder(), get_store())


def get_corpus_ingester() -> CorpusIngester:
    return CorpusIngester(EdgarSource(), get_embedder(), get_store())
