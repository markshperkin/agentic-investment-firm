# server

FastAPI backend + the multi-agent firm.

Houses: the LangGraph orchestrator, the six agents, the RAG layer (Chroma + Voyage embeddings), the deterministic risk engine, the paper broker, persistent state (SQLite + SQLAlchemy), the trace/event store, and the ingestion pipeline.

See [`../docs/architecture.md`](../docs/architecture.md).
