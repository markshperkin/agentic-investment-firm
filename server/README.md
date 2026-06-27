# server

FastAPI backend + the multi-agent firm.

Houses: the deterministic orchestrator (`firm/runner.py` + `firm/dispatcher.py`), the
reasoning agents, the RAG layer (Chroma + Voyage embeddings, with deterministic fakes
offline), the deterministic risk engine, the paper broker, persistent state (SQLite +
SQLAlchemy), the trace/event store, the ingestion pipeline, reporting (dashboard +
Excel), and the offline eval harness (`eval/`).

```bash
pip install -e ".[dev]"
python -m pytest -q          # full suite
python -m eval.harness       # golden + red-team eval → ../docs/eval-report.md
uvicorn app.main:app --reload --port 8000
```

See [`../docs/architecture.md`](../docs/architecture.md) and
[`../docs/runbook.md`](../docs/runbook.md). Orchestration choice:
[`../docs/why-not-langgraph.md`](../docs/why-not-langgraph.md).
