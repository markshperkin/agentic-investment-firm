# Handoff — Agentic Investment Firm build

Resume point for a fresh context window. Written 2026-06-24.

## Goal
Cato Networks home task: a multi-agent paper-trading investment firm replaying one US trading day.
Priorities (in order): **agentic pipeline → guardrails → observability.** Reliability + safety over features.
Full design: `docs/architecture.md`. Task list + status: `docs/plan.md` (checkboxes). Decisions: `docs/adrs/`.

## Repo / branch
- GitHub: `markshperkin/agentic-investment-firm` (public). Monorepo: `server/` (FastAPI+agents), `web/` (React), `docs/`.
- Work is on branch **`build/foundation`** (NOT yet merged to `main`). Every task committed + pushed.
- Assignment brief is gitignored (do not commit it).

## Environment constraints (important)
- Sandbox network is walled. **pip** works only with `--trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org`.
- **npm registry is unreachable here** → the React app builds on the USER's machine (`cd web && npm install && npm run build` — already verified passing once).
- Live EDGAR / Voyage / Chroma / Anthropic all need network or keys → they run on the user's machine. Tests use deterministic fakes (`FakeEmbedder`, `FakeFilingSource`, `InMemoryVectorStore`) and a scripted/cassette LLM provider.
- Run tests: `cd server && source .venv/Scripts/activate && python -m pytest -q` → currently **44 passing**.

## Key design decisions made during build (some deviate from architecture.md)
1. **HITL is a DB-backed approval queue, NOT a LangGraph interrupt.** The orchestrator is a deterministic `firm/runner.py` loop. Pending approvals persist in the `approvals` table (survives restart). This is simpler/robust for web-driven approval. **Reconcile architecture.md + ADR-001 to reflect this** (or note as an accepted deviation).
2. RAG providers are swapped by config; tests use fakes. **Cleanup pending** (see memory `cleanup-rag-fakes`): remove the silent production fallback to `FakeEmbedder`/`InMemoryVectorStore` in `rag/factory.py` — live mode should require VOYAGE_API_KEY + Chroma and fail loudly.
3. LLM cost-routing: Haiku default, Sonnet for `pm`/`risk` (`llm/router.py:TASK_MODEL`).

## What's DONE (T01–T16, all tested)
- T01 scaffold (FastAPI, SQLite/SQLAlchemy, config, `/health`)
- T02 LLM router (cost-aware, cassette + Anthropic providers, schema-validated output)
- T03 trace/span store + `/runs/{id}/feed` (observability spine; spans persist on start, update on close)
- T04 WS `/stream` + React event-feed UI (collapsible output) + Portfolio view + tab shell
- T05 Docker (multi-stage: builds web, FastAPI serves it) + compose — image build unverified (no Docker here)
- T06 portfolio state + deterministic paper broker (slippage/commission/market-hours, transactional, idempotent)
- T07 price ingester (yfinance, lazy) + `DataAsset` catalog + `/datasets` + lookahead-safe price feed (parquet)
- T08 replay clock + deterministic dispatcher + runner (TICK spans step the day)
- T09 corpus pipeline: EDGAR source (lazy), chunker, embedder iface, vector store iface, time-boxed retriever, **lookahead guardrail**
- T10 Query-Gen + Relevance-Critic agents + **CRAG loop** (retry-on-bad-retrieval, refusal on exhaustion)
- T11 Research agent + **citation/numeric verifier** (cited numbers must appear in the source chunk)
- T12 PM agent + deterministic sizer + **append-only TickerMemory** belief timeline
- T13 **risk engine** (hard limits) + risk agent + **DB-backed HITL** (approve/edit/reject, engine re-check on edit)
- T14 **CONTEXT_BUILD pipeline end-to-end** (CRAG→research→PM→risk→HITL) + partial-failure isolation
- T15 schema/semantic validation + **prompt-injection quarantine** (in retriever)
- T16 **resource circuit-breaker** (per-run call/token/time budget → `BUDGET_EXCEEDED` halt)

## Code map (server/app)
- `firm/` — runner.py (tick loop + budget + partial-failure), dispatcher.py (deterministic routing), clock.py, pipeline.py (per-ticker chain), hitl.py (submit/resolve approval), memory.py (TickerMemory)
- `agents/` — query_gen, relevance_critic, research, pm, risk + schemas.py (all Pydantic contracts)
- `rag/` — edgar.py, chunker.py, embeddings.py, vector_store.py, ingest.py, retriever.py, crag.py, factory.py
- `guardrails/` — lookahead.py, citations.py, injection.py, risk_engine.py, budget.py
- `state/` — broker.py, portfolio.py (incl. account_snapshot), sizing.py, market_hours.py
- `obs/` — spans.py (emitter + contextvars), stream.py (WS broadcaster)
- `data/` — prices.py, price_feed.py, catalog.py
- `llm/` — router.py, factory.py, base.py, pricing.py, providers/{cassette,anthropic}.py
- `api/` — health, feed, stream, portfolio, datasets, run, approvals
- `models/` — span, portfolio, dataset, corpus, ticker_memory, approval

## REMAINING (T17–T24) — next session
- **T17** INCREMENTAL_NEWS + PRICE_REEVAL dispatch paths. Wire handlers in `runner.py`/`pipeline.py`. INCREMENTAL_NEWS: new doc since last tick → push to Research (skip CRAG). PRICE_REEVAL: reuse latest TickerMemory view + new price → PM→risk. Dispatcher already returns these paths; need handlers + `has_new_docs`/`has_stop_trigger` signals (query Document by published_ts in (last_tick, as_of]).
- **T18** DAY_REVIEW (load day context + delta-retrieve + EOD framing → hold/trim/flatten) + MONITOR_SELL (stop/target → protective sell deterministic).
- **T19** on-demand ticker ingestion is mostly done (`POST /datasets`); add a `web/` ticker-search panel + make `ready_days` require PRICES+CORPUS once corpus runs live.
- **T20** Reporting agent + Excel (`openpyxl`) + dashboard report view. 2 channels = dashboard + Excel. Pull numbers from Portfolio store, not LLM.
- **T21** Observability views: feed filters, belief-evolution view (`GET /tickers/{sym}/memory` — add endpoint reading TickerMemory series), cost rollup, Export (JSONL) + Reset (`POST /admin/reset`) endpoints + buttons.
- **T22** Eval harness + golden dataset (+ red-team injection/over-limit slice) + GitHub Actions CI. Return metrics (P&L vs SPY) + process metrics (groundedness, refusal correctness, guardrail block-rate). Use cassettes for determinism. `docs/eval-report.md`.
- **T23** Crash recovery: on boot, reconcile APPROVED-but-unfilled via idempotency key; verify `cash + Σholdings = equity`.
- **T24** Sample run (commit one replayed day's reports + trace JSONL) + README clone→demo <10min + runbook + architecture diagram + eval report.

## Open follow-ups (memories)
- `cleanup-rag-fakes` — remove silent prod fallback to fake embedder/store.
- `run-circuit-breaker-followup` — measure a normal run, set real budget limits, open a GitHub issue (now that repo exists, T16's budget is in but limits are guesses).
- No Claude co-author on commits (user preference).
- pip needs `--trusted-host`.

## Suggested next-session opening
"Read docs/handoff.md, docs/plan.md, docs/architecture.md. Continue the build on branch build/foundation from T17. Run `cd server && source .venv/Scripts/activate && python -m pytest -q` to confirm 44 green, then implement T17."
