# Implementation Plan — Agentic Investment Firm

- Source: `docs/architecture.md` (no `specs/`; architecture is the planning source)
- Generated: 2026-06-24
- Build window: 3–4 days, solo + AI assist
- Priority order: **agentic pipeline → guardrails → observability**

## Scope reality check (read first)

The full architecture is ~5–7 honest dev-days. In 3–4 days we ship a **coherent, demoable spine that is excellent on the three priorities** and *honestly* partial elsewhere. Tasks are tagged **[CORE]** (must ship for a credible demo) or **[STRETCH]** (cut first if time runs out). Guiding principle: **observability-first** — build the trace/event store early so every feature is observable as it lands, and keep an end-to-end path working from Wave 1 onward (tracer-bullet), then deepen.

Modes: **AFK** = agent can ship solo · **HITL** = needs your judgement/decision.

---

## Progress

- [x] T01 — Server scaffold + DB + config (health endpoint; 1 test passing)
- [x] T02 — LLM Router (Anthropic + cassette; routing, validation, cost, spans; 2 tests)
- [x] T03 — Trace/span store + event emitter (spans persist, nest, feed ordered; 3 tests)
- [x] T04 — Web scaffold + live feed shell (WS streaming backend tested; React event feed builds clean — verified `npm run build`)
- [~] T05 — Docker + compose (multi-stage Dockerfile + compose written; image build unverified — needs network/Docker)
- [x] T06 — Portfolio state + paper broker (transactional fills, slippage/commission, idempotency; 6 tests + Portfolio UI — verify `npm run build`)
- [x] T07 — Price ingester + DataAsset catalog + /datasets + lookahead-safe price feed (4 tests; live yfinance fetch runs locally)
- [x] T08 — Replay clock + deterministic dispatcher + runner (TICK spans step the day; 3 tests)
- [x] T09 — Corpus pipeline + time-box + lookahead guardrail (logic tested w/ fakes; live EDGAR/Voyage/Chroma run locally; 3 tests)
- [x] T10 — Query-Gen + Relevance-Critic + CRAG loop (retry-on-bad-retrieval, refusal on exhaustion; 3 tests)
- [x] T11 — Research agent + citation/numeric-consistency verifier (cited numbers must appear in source; 3 tests)
- [x] T12 — PM agent + deterministic sizer + append-only TickerMemory timeline (4 tests)
- [x] T13 — Risk engine (hard limits) + Risk agent + DB-backed HITL approvals (approve/edit/reject, engine re-check on edit; 7 tests)
- [x] T14 — CONTEXT_BUILD pipeline end-to-end (CRAG→research→PM→risk→HITL) + partial-failure isolation (1 e2e test)
- [x] T15 — Schema/semantic validation + prompt-injection quarantine (2 tests)
- [x] T16 — Resource circuit-breaker (per-run call/token/time budget → BUDGET_EXCEEDED halt; 2 tests)
- [ ] T17 — INCREMENTAL_NEWS + PRICE_REEVAL paths
- [ ] T18 — DAY_REVIEW + MONITOR_SELL
- [ ] T19 — On-demand ticker ingestion [STRETCH]
- [ ] T20 — Reporting agent + Excel + dashboard report
- [ ] T21 — Observability views + export/reset
- [ ] T22 — Eval harness + golden dataset + CI
- [ ] T23 — Crash recovery + reconciliation
- [ ] T24 — Sample run + docs

## Wave 0 — Foundation (infra; horizontal allowed)

### T01 — Server scaffold + DB + config  [CORE]
- Slice: `GET /health` returns liveness + DB-invariant check; app boots with SQLite via SQLAlchemy.
- Mode: AFK · Complexity: S
- Files: create `server/pyproject.toml`, `server/app/main.py`, `server/app/db.py`, `server/app/config.py`, `server/.env.example`, `server/app/models/__init__.py`
- Depends: none
- AC: app starts; `/health` 200; `.env.example` committed (empty keys); SQLite file created on boot.

### T02 — LLM Router (Anthropic + cassette/mock provider)  [CORE]
- Slice: one `router.complete(task, schema)` call returns a schema-validated object from Anthropic live, or from a recorded cassette when `LLM_MODE=cassette`.
- Mode: AFK · Complexity: M
- Files: create `server/app/llm/router.py`, `server/app/llm/providers/{anthropic,cassette}.py`, `server/app/llm/cassettes/`
- Depends: T01
- AC: Haiku default / Sonnet escalation by task tag; cassette mode needs no key; per-call tokens+cost returned.

### T03 — Trace/span store + event emitter  [CORE] (observability spine)
- Slice: any code path can open/close a span; spans persist to SQLite on start (PENDING) + update on close; `GET /runs/{id}/feed` returns time-ordered events.
- Mode: AFK · Complexity: M
- Files: create `server/app/obs/spans.py`, `server/app/models/span.py`, `server/app/api/feed.py`; modify `main.py`
- Depends: T01
- AC: span has run/tick/span ids, kind, status, in/out json, tokens, cost, latency; survives restart (re-read from DB); feed ordered by time.

### T04 — Web scaffold + live feed shell  [CORE]
- Slice: React app loads, connects `WS /stream`, renders the event feed (rows append live; collapsible raw output, collapsed by default).
- Mode: AFK · Complexity: M
- Files: create `web/` (Vite+TS), `web/src/api.ts`, `web/src/views/EventFeed.tsx`; modify `server` to expose `WS /stream`
- Depends: T03
- AC: feed shows events live + re-hydrates from `/runs/{id}/feed` on reload.

### T05 — Docker + compose  [CORE]
- Slice: `docker compose up` boots server (serving built web) + volumes for SQLite/Chroma.
- Mode: AFK · Complexity: S
- Files: create `server/Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Depends: T01, T04
- AC: clone → `docker compose up` → app reachable; data persists across restarts.

---

## Wave 1 — State + clock spine (tracer bullet)

### T06 — Portfolio state + paper broker  [CORE]
- Slice: a hardcoded BUY fills via the deterministic broker (slippage+commission, market-hours), book updates transactionally, `GET /portfolio` shows it.
- Mode: AFK · Complexity: M
- Files: create `server/app/state/{portfolio,broker}.py`, `server/app/models/{position,trade}.py`, `server/app/api/portfolio.py`, `web/src/views/Portfolio.tsx`
- Depends: T01, T03
- AC: cash/holdings/cost-basis update atomically; fill emits spans; invariant `cash+Σholdings=equity` holds.

### T07 — Frozen market data loader + price feed  [CORE]
- Slice: ingest one day (+ lookback) of prices via yfinance → commit parquet; `price_feed(ticker, as_of)` returns only `≤ as_of` bars.
- Mode: HITL (pick the day/tickers) · Complexity: M
- Files: create `server/app/data/ingest_prices.py`, `server/app/data/price_feed.py`, `server/data/prices/*.parquet`
- Depends: T01
- AC: deterministic offline reads; future bars never returned; SPY included.

### T08 — Replay clock + dispatcher skeleton (SKIP only)  [CORE]
- Slice: `POST /run/replay {date,tickers}` steps hourly open→close, each tick emits a TICK span; all ticks route to SKIP for now; feed shows the day stepping.
- Mode: AFK · Complexity: M
- Files: create `server/app/firm/clock.py`, `server/app/firm/dispatcher.py`, `server/app/api/run.py`
- Depends: T03, T06, T07
- AC: ~7 ticks, correct `as_of` each; SKIP spans show reason; reproducible across runs.

---

## Wave 2 — RAG + the agent pipeline (the heart)

### T09 — Corpus ingestion (SEC EDGAR) + Chroma + time-box + lookahead assert  [CORE]
- Slice: ingest EDGAR filings (10-K/10-Q/8-K, dated by acceptance datetime) for default tickers → chunk → Voyage embed → Chroma; retriever filters `≤ as_of`; boundary assertion rejects any future-dated chunk.
- Mode: HITL (curate corpus) · Complexity: L
- Files: create `server/app/rag/{ingest,retriever,timebox}.py`, `server/app/guardrails/lookahead.py`, `server/data/corpus/`
- Depends: T01
- AC: persisted vectors (no re-embed on rerun); retrieval respects `as_of`; lookahead violation aborts run with span.

### T10 — Query-Gen → Retrieve → Relevance-Critic (CRAG loop)  [CORE]
- Slice: a research request runs query-gen → retrieve → critic; on bad retrieval, reformulates from the critique (max 2); each attempt traced.
- Mode: AFK · Complexity: L
- Files: create `server/app/agents/{query_gen,relevance_critic}.py`, `server/app/rag/crag.py`
- Depends: T02, T03, T09
- AC: failure_kind → strategy mapping works; exhaustion → INSUFFICIENT_EVIDENCE; attempts visible in feed.

### T11 — Research agent + citation/numeric verifier  [CORE]
- Slice: research turns graded chunks into a typed view with citations; the verifier strips any uncited claim / number not present in the cited chunk.
- Mode: AFK · Complexity: M
- Files: create `server/app/agents/research.py`, `server/app/guardrails/citations.py`
- Depends: T10
- AC: every numeric claim maps to a chunk whose text contains it; else stripped or INSUFFICIENT_EVIDENCE.

### T12 — PM agent + TickerMemory + sizing  [CORE]
- Slice: PM turns a view + portfolio into a TradeProposal with a thesis_card; confidence<threshold → NoTrade; TickerMemory row written per tick.
- Mode: AFK · Complexity: M
- Files: create `server/app/agents/pm.py`, `server/app/state/sizing.py`, `server/app/models/ticker_memory.py`
- Depends: T06, T11
- AC: thesis_card claims all cited; sizing clamped to cash; append-only memory rows persist.

### T13 — Risk engine + Risk agent + HITL interrupt + approvals  [CORE]
- Slice: every BUY hits the deterministic engine (hard limits); legal buys `interrupt()` and appear in the Approvals inbox; approve/edit/reject resumes the graph and executes.
- Mode: HITL (UX review) · Complexity: L
- Files: create `server/app/guardrails/risk_engine.py`, `server/app/agents/risk.py`, `server/app/api/approvals.py`, `web/src/views/Approvals.tsx`
- Depends: T06, T12
- AC: illegal trades rejected pre-human; graph state survives the wait + restart; edit re-runs engine; decision recorded (approver).

### T14 — Wire CONTEXT_BUILD path end-to-end (LangGraph)  [CORE]
- Slice: open tick runs query-gen→…→research→PM→risk→HITL→execution→trace, across the watched universe — the full happy path, demoable.
- Mode: AFK · Complexity: M
- Files: create `server/app/firm/graph.py`, `server/app/firm/context_assembler.py`; modify `dispatcher.py`
- Depends: T08, T13
- AC: one full trade flows trigger→fill with a complete feed; checkpointer persists FirmState.

---

## Wave 3 — Remaining paths + guardrail completeness

### T15 — Input/schema/semantic validation + injection defense  [CORE]
- Slice: all agent I/O + API inputs validated (shape + sanity); retrieved text delimited/spotlighted; injection-pattern chunks quarantined.
- Mode: AFK · Complexity: M
- Files: create `server/app/guardrails/{validation,injection}.py`; modify agent boundaries
- Depends: T11
- AC: qty>0/confidence∈[0,1] enforced; seeded injection chunk quarantined + traced.

### T16 — Resource circuit-breaker  [CORE]
- Slice: per-run token/call/wall-clock budget; breach halts run cleanly with BUDGET_EXCEEDED span + partial report.
- Mode: AFK · Complexity: S
- Files: create `server/app/guardrails/budget.py`; modify `graph.py`
- Depends: T14
- AC: low budget → clean halt + partial report (no crash). *(Set limits after measuring a normal run.)*

### T17 — INCREMENTAL_NEWS + PRICE_REEVAL paths  [CORE]
- Slice: a mid-day new doc pushes straight to Research (skip CRAG); a price move ≥2% re-evaluates via PM with cached view — dispatcher routes both.
- Mode: AFK · Complexity: M
- Files: modify `dispatcher.py`, `graph.py`; create path handlers
- Depends: T14
- AC: dispatcher picks correct path; dedup via processed_doc_ids; both traced.

### T18 — DAY_REVIEW (EOD framing) + MONITOR_SELL  [CORE]
- Slice: pre-close tick loads day context + delta-retrieves + injects EOD framing → hold/trim/flatten decisions; stop/target triggers protective sell.
- Mode: AFK · Complexity: M
- Files: modify `dispatcher.py`, `graph.py`; create `server/app/firm/monitor.py`
- Depends: T17
- AC: EOD decisions consider gap risk; protective sell deterministic; both traced.

### T19 — On-demand ticker ingestion  [STRETCH]
- Slice: `POST /tickers {symbol}` fetches prices + corpus, embeds, persists; UI search adds a tradeable ticker.
- Mode: AFK · Complexity: M
- Files: create `server/app/api/tickers.py`; modify ingest; `web/src/views/Tickers.tsx`
- Depends: T07, T09
- AC: new ticker persisted + tradeable next run; lookahead-safe.

---

## Wave 4 — Reporting, observability views, eval, demo

### T20 — Reporting agent + Excel + dashboard report  [CORE] (2nd channel)
- Slice: end-of-day report (positions, P&L vs SPY, decision log w/ citations) renders to dashboard + downloadable `.xlsx`.
- Mode: AFK · Complexity: M
- Files: create `server/app/agents/reporting.py`, `server/app/reports/excel.py`, `server/app/api/reports.py`, `web/src/views/Report.tsx`
- Depends: T14
- AC: two channels produced; numbers pulled from store (not LLM); committed with sample run.

### T21 — Observability views: feed polish + belief-evolution + cost + export/reset  [CORE]
- Slice: feed filters (ticker/trade), collapsible outputs; belief-evolution timeline per ticker; cost rollup; Export (JSONL) + Reset buttons.
- Mode: AFK · Complexity: M
- Files: create `web/src/views/{Beliefs,Cost}.tsx`; `server/app/api/{export,admin}.py`; modify feed UI
- Depends: T03, T12, T20
- AC: replay-from-trace satisfiable in UI; export downloads JSONL; reset clears store (confirm-gated).

### T22 — Eval harness + golden dataset (+ red-team) + CI  [CORE]
- Slice: cassette-replayed run computes return metrics (vs SPY) + process metrics (groundedness, refusal, guardrail block-rate); runs in GitHub Actions, zero tokens.
- Mode: HITL (record cassettes, label golden cases) · Complexity: L
- Files: create `server/eval/{harness,golden,redteam}.py`, `docs/eval-report.md`, `.github/workflows/ci.yml`
- Depends: T14, T15
- AC: CI green offline; report has return AND process metrics; red-team block-rate reported.

### T23 — Crash recovery + reconciliation  [CORE]
- Slice: kill the process mid-cycle; on restart it reconciles APPROVED-but-unfilled trades via idempotency key and verifies the equity invariant.
- Mode: AFK · Complexity: M
- Files: create `server/app/state/reconcile.py`; modify boot
- Depends: T06, T14
- AC: no double-fill; invariant restored; reconciliation traced.

### T24 — Sample run + docs (README/runbook/diagram/eval)  [CORE]
- Slice: replay one full committed day → commit reports + trace JSONL; README gets clone→demo <10 min; runbook + architecture diagram + eval report.
- Mode: HITL (narrative + diagram) · Complexity: M
- Files: create `docs/{runbook,architecture-diagram}.md`, `docs/sample-run/`; modify root `README.md`
- Depends: T20, T22
- AC: reviewer clones → demos in <10 min; sample artifacts present; reports honest.

---

## Dependency Graph (condensed)

```
T01 → T02, T03, T06, T07, T09
T03 → T04 → T05
T06,T07 → T08
T02,T09 → T10 → T11 → T12 → T13 → T14
T08 ─────────────────────────────→ T14
T14 → T16, T17 → T18 ; T14 → T20 → T21 ; T14,T15 → T22 ; T14 → T23 → ; T20,T22 → T24
T11 → T15 ; T07,T09 → T19
```

## Critical Path

`T01 → T02 → T09 → T10 → T11 → T12 → T13 → T14 → T22 → T24`
The agent pipeline (T09–T14) is the long pole; evals (T22) and the demo packaging (T24) gate the finish. **Protect this chain.**

## Execution waves (parallelism)

- **Day 1:** Wave 0 (T01–T05) + start T06/T07. Get the feed + a hardcoded fill visible.
- **Day 2:** T08 + RAG/agents T09–T12. Pipeline producing grounded proposals.
- **Day 3:** T13–T18 (HITL, full graph, paths, guardrails). End-to-end trade with approval.
- **Day 4:** T20–T24 (reporting, obs views, eval, sample run, docs). Cut STRETCH (T19) first.

## Risk Areas

- **T09/T10 (RAG+CRAG)** — biggest single chunk (L+L). If slipping, ship CONTEXT_BUILD with a simpler retrieve and add the full CRAG loop only if time allows.
- **T13 (HITL+LangGraph interrupt/resume)** — the trickiest integration; front-loaded review recommended. Spike the interrupt/resume early.
- **T22 (eval/cassettes)** — cassette recording is fiddly; record as you build each agent, not at the end.
- **OneDrive + git** — repo lives under a synced folder; watch for lock/line-ending noise.
- **3–4 day window is aggressive** — the CORE set alone is ~full; STRETCH (T19) and any polish are optional.

## Unresolved questions (carry from architecture)

- Sample replay day + ticker set — pick a day w/ real citable news (blocks T07, T09, T22).
- HITL thresholds — confirm max-position 10% / max-order $25k / max-daily-loss 3%.
- Circuit-breaker limits — set after measuring a normal run (T16).
- Voyage vs local embeddings default for the committed corpus (T09).
- 2nd channel confirmed Excel; Slack stays cut.
