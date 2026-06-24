# Architecture — The AI Investment Firm

> Reads from `docs/prd.md`. Designs the multi-agent paper-trading system.
> Design priority (from PRD): **agentic system → guardrails → observability**. Reliability and safety over features.

## System Overview

A self-contained multi-agent system that runs an AI investment desk for one replayed US trading day. Six reasoning agents (Query-Gen, Relevance-Critic, Research, Portfolio Manager, Risk, Reporting) collaborate over a **LangGraph** state graph, with deterministic code handling control flow, retrieval, risk enforcement, and execution. Decisions are grounded in a **time-boxed RAG corpus** with mandatory citations; trades flow through a **deterministic risk engine** that the LLM cannot bypass and pause for a **human Risk Committee** when over threshold. Every agent invocation, tool call, and trade is written to a **durable trace store** so a reviewer can replay any trade from the trace alone. A **FastAPI** backend exposes state + approvals + traces to a **React** dashboard. The whole thing runs deterministically offline (frozen market data + recorded LLM responses) so the eval harness runs in CI with zero token spend.

Primary quality attributes: **correctness/safety** (hard limits cannot be exceeded), **auditability** (replay-from-trace), **groundedness** (no uncited numbers), **reproducibility** (deterministic replay), **crash-recoverability** (transactional state).

## Component Diagram

```
                              ┌──────────────────────────────────────────────┐
                              │                React Dashboard                │
                              │  Portfolio │ Approvals Inbox │ Trace Viewer   │
                              └───────▲───────────▲────────────────▲──────────┘
                                REST  │      WS/SSE│ (live ticks)   │ REST
                              ┌───────┴────────────┴────────────────┴──────────┐
                              │                 FastAPI Backend                 │
                              │  /portfolio /trades /approvals /tickers         │
                              │  /run/replay /runs/{id}/trace /reports  /stream │
                              └───┬─────────────┬───────────────┬───────────┬───┘
                                  │             │               │           │
                   ┌──────────────▼──┐   ┌──────▼───────┐  ┌────▼─────┐ ┌───▼────────┐
                   │  LangGraph Firm  │   │ Risk Engine  │  │  Trace   │ │ Ingestion  │
                   │   Orchestrator   │   │(deterministic│  │  Store   │ │  Pipeline  │
                   │                  │   │  guardrail)  │  │          │ │(new ticker)│
                   │  ┌────────────┐  │   └──────────────┘  └──────────┘ └─────┬──────┘
                   │  │ Query-Gen  │  │          ▲                              │
                   │  │ Rel-Critic │  │          │ enforce hard limits          │ fetch+embed
                   │  │ Research   │──┼──────────┘ (retriever, risk engine,      │
                   │  │ PM         │  │   interrupt()  exec broker = det. code)  │
                   │  │ Risk       │  │                                          ▼
                   │  │ Reporting  │  │                              ┌────────────────────┐
                   │  └─────┬──────┘  │                              │  External (ingest- │
                   └────────┼─────────┘                              │  time only):       │
                            │ tools                                  │  yfinance, EDGAR,  │
            ┌───────────────┼────────────────┬──────────────┐       │  news feeds        │
            ▼               ▼                ▼              ▼        └────────────────────┘
   ┌────────────────┐ ┌───────────┐  ┌──────────────┐ ┌───────────┐
   │ RAG Retriever  │ │ Market    │  │ Portfolio    │ │ LLM Router│
   │ Chroma (vec) + │ │ Data      │  │ Store (state)│ │ Anthropic │
   │ Voyage/local   │ │ (frozen   │  │ SQLite +     │ │ Haiku→    │
   │ embeddings     │ │ snapshot) │  │ SQLAlchemy   │ │ Sonnet    │
   └────────────────┘ └───────────┘  └──────────────┘ └───────────┘
            ▲                                ▲
   ┌────────┴────────┐              ┌────────┴────────┐
   │ Corpus (docs,   │              │ LangGraph       │
   │ time-boxed,     │              │ Checkpointer    │
   │ committed)      │              │ (SqliteSaver)   │
   └─────────────────┘              └─────────────────┘
```

**Trust boundary:** everything inside the LangGraph box is *agent reasoning* and is **untrusted** w.r.t. money. The **Risk Engine** and **Portfolio Store** are deterministic code; they are the only things allowed to mutate the book, and they enforce limits regardless of what an agent "decides." Retrieved corpus/news text is **untrusted input** (prompt-injection surface) and is never allowed to issue tool calls.

## Agent Design

**6 reasoning agents** (LLM): Query-Gen, Relevance-Critic, Research, PM, Risk, Reporting. Control flow + money-touching steps are **deterministic code, not agents**: the orchestrator (LangGraph graph), the retriever, the risk engine, the paper broker (execution), and the monitoring loop. Each agent has a **typed contract** (Pydantic in/out), **declared tools**, **defined failure modes**. All LLM outputs are schema-validated; a parse failure triggers a bounded retry, then a typed failure. **Every agent call, tool call, grader verdict, engine decision, and broker write emits a trace span** (see Observability).

### 1. Query-Generation Agent
- **Input:** `QueryRequest{ ticker, as_of_date, intent: RESEARCH_ENTRY|SELL_REVIEW, prior_attempts: list[QueryAttempt], critique?: RelevanceGrade }`
- **Output:** `QueryPlan{ queries: list[str], filters: {ticker, date_window}, strategy: BASELINE|DECOMPOSE|STEPBACK|HYDE|FILTER_FIX }`
- **Role:** plans *what to retrieve*, not just *retrieve*. On a retry it **reasons from the grader's critique** (see Pipeline Mechanics) to reformulate — never reissues a query already in `prior_attempts`.
- **Tools:** none (pure planning). Retrieval is performed by the deterministic retriever using the plan.
- **Failure modes:** out of retry budget → signals Research to refuse (`INSUFFICIENT_EVIDENCE`).

### 2. Relevance-Critic Agent
- **Input:** `GradeRequest{ ticker, as_of_date, query_plan, retrieved_chunks: list[Chunk] }`
- **Output:** `RelevanceGrade{ relevant: bool, coverage: 0–1, missing: str, failure_kind: NO_HITS|WRONG_ENTITY|STALE|TOO_GENERIC|OFF_TOPIC, fix_hint: str }`
- **Role:** judges whether retrieved chunks actually answer the intent, and when they don't, **explains why** + a fix hint. This critique is the reasoning signal that steers the next Query-Gen pass (see Pipeline Mechanics). Runs on a cheap model (Haiku) — it is in the retry loop, so it must stay cheap.
- **Tools:** none (pure judgement over the retrieved set).
- **Failure modes:** ambiguous → defaults to `relevant=false` with `failure_kind=TOO_GENERIC` (fail safe toward more grounding, never pass weak evidence through).

### 3. Research Agent
- **Input:** `ResearchRequest{ ticker, as_of_date, retrieved_chunks: list[Chunk], price_features }`
- **Output:** `ResearchView{ ticker, stance: BULLISH|BEARISH|NEUTRAL|INSUFFICIENT_EVIDENCE, confidence: 0–1, key_points: list[KeyPoint], citations: list[Citation{chunk_id, source, published_date, quote}] }`
- **Role:** extracts grounded key points from *already-retrieved, relevance-passed* chunks. Does not retrieve (that's the query-gen + retriever loop upstream).
- **Tools:** `get_price_features(ticker, as_of_date)` (returns/vol from frozen data).
- **Failure modes:** insufficient/irrelevant evidence → `INSUFFICIENT_EVIDENCE` (refusal, no thesis); every non-neutral claim **must** carry ≥1 citation or the citation verifier strips it.

### 4. Portfolio Manager (PM) Agent
- **Input:** `PMRequest{ research_view, portfolio_snapshot, cash, decisions_today }`
- **Output:** `TradeProposal{ ticker, side: BUY|SELL, quantity, est_notional, thesis_card, research_ref }` or `NoTrade{reason}`
- **`thesis_card`** (the credibility object surfaced to the human) — `{ headline, why_now, expected_edge, key_evidence: list[Citation], risks, confidence }`. Every claim traces to a cited corpus chunk. This is what the Risk Committee reads before approving.
- **Policy:** acts only when `confidence ≥ act_threshold` (default 0.6); a *negative* view → `NoTrade` (it does **not** loop back to dig for a buy reason). At most one trade proposal per cycle.
- **Tools:** `get_quote(ticker, as_of)`, `position_sizer(...)` (deterministic, confidence-scaled %-of-equity, clamped to cash + limits).
- **Failure modes:** no actionable/refused view → `NoTrade`; thesis_card with any uncited claim is rejected by the guardrail before reaching the human.

### 5. Risk Agent
- **Input:** `RiskRequest{ proposal: TradeProposal, engine_result: RiskEngineResult, portfolio_snapshot }`
- **Output:** `RiskAssessment{ decision: REQUIRE_HUMAN|REJECT, breaches: list[LimitBreach], reasoning, severity }`
- **Policy:** the **deterministic risk engine runs first** and hard-`REJECT`s any illegal trade before a human is ever involved. **Every legal BUY → `REQUIRE_HUMAN`** (no silent auto-buy). Risk-reducing SELLs may auto-approve unless they breach a limit. The agent *explains and packages* the engine verdict in human terms; it cannot overturn it.
- **Tools:** consumes `risk_engine.evaluate(...)` output (the engine is deterministic code, run by the orchestrator).
- **Failure modes:** hard breach → `REJECT` (engine-forced); otherwise BUY → `REQUIRE_HUMAN` with thesis_card attached.

### 6. Reporting Agent
- **Input:** `ReportRequest{ date, trades, pnl, decisions_with_citations, benchmark }`
- **Output:** `DailyReport{ summary, positions, trades, pnl_vs_spy, decision_log }` → rendered to **Excel** + **dashboard** (≥2 channels).
- **Failure modes:** missing data → partial report flagged `INCOMPLETE`; never invents numbers (pulls from Portfolio Store, not LLM memory).

### Deterministic components (not agents)
- **Orchestrator** — LangGraph graph; conditional edges decide the next node. Control flow is **code, not an LLM**, so every run of the same day routes identically (reproducible, auditable).
- **Retriever** — deterministic; runs the Query-Gen plan against Chroma with the time-box filter. (Grading the result is the Relevance-Critic agent, above.)
- **Risk engine** — deterministic rule checker; the only gate to the book (see Guardrails).
- **Paper broker (execution)** — `paper_broker.execute(...)`: slippage + commission + market-hours check, writes the fill **transactionally** to the Portfolio Store. Re-checks limits immediately before fill (state may have changed during the HITL wait). Failure modes: market closed → reject; post-wait limit breach → reject; partial-write impossible (single transaction).
- **Monitoring loop** — steps the replay clock over held positions; on a price move / new news / stop-trigger it launches a SELL review (protective sells fire deterministically; discretionary sells re-enter the pipeline). See Pipeline Mechanics.

### Orchestration Flow (LangGraph — deterministic control)

```
 TRIGGER (scheduled tick OR event: news/price move)
        │
        ▼
 ┌──────────────┐   ◄────────────── critique (RelevanceGrade) ──────────┐
 │  QUERY-GEN   │  plans queries (reasons from critique on retries)      │
 └──────┬───────┘                                                        │
        ▼ QueryPlan                                                      │
 ┌──────────────┐                                                        │
 │  RETRIEVE    │  deterministic; time-boxed (published_date ≤ as_of)    │
 └──────┬───────┘                                                        │
        ▼ chunks                                                         │
 ┌──────────────┐   not relevant ──► reformulate (max 2 retries) ────────┘
 │ RELEVANCE    │   still bad after budget ──► INSUFFICIENT_EVIDENCE ──┐
 │ GRADE (cheap)│                                                      │
 └──────┬───────┘                                                      │
        ▼ relevant                                                     │
 ┌──────────────┐                                                      │
 │  RESEARCH    │  grounded key points + citations                     │
 └──────┬───────┘                                                      │
        ▼ ResearchView                                                 │
 ┌──────────────┐  negative/refused view ──► NoTrade ──────────────────┤
 │     PM       │  (no loop-back to "find a buy reason")                │
 └──────┬───────┘                                                      │
        ▼ TradeProposal (+ thesis_card)                                │
 ┌──────────────┐  hard-limit breach ──► REJECT (logged) ──────────────┤
 │ RISK ENGINE  │  (deterministic; runs before any human)              │
 └──────┬───────┘                                                      │
        ▼ legal                                                        │
 ┌──────────────┐                                                      │
 │ RISK AGENT   │  packages engine verdict → human-readable case        │
 └──────┬───────┘                                                      │
        ▼ REQUIRE_HUMAN (every buy)                                    │
 ┌──────────────────┐  interrupt(): graph pauses, checkpoint persists; │
 │ ★ HITL COMMITTEE │  human reads thesis_card + citations;            │
 │   approve/edit/  │  resumes on POST /approvals/decide               │
 │   reject         │  (edit → re-run risk engine)                     │
 └──────┬───────────┘  reject ─────────────────────────────────────────┤
        ▼ approve/edit                                                 │
 ┌──────────────┐  pre-fill limit re-check; market-hours check         │
 │  EXECUTION   │  (paper broker, transactional)                       │
 └──────┬───────┘                                                      │
        ▼ Fill                                                         │
 ┌──────────────┐  steps clock over held positions; on price move /    │
 │ MONITORING   │  news / stop → SELL review (protective=deterministic,│
 │   LOOP       │  discretionary=re-enter pipeline)                    │
 └──────┬───────┘                                                      │
        ▼ end of day                                                   │
 ┌──────────────┐◄─────────────────────────────────────────────────────┘
 │  REPORTING   │  DailyReport → Excel + Dashboard
 └──────┬───────┘
        ▼ [END]
```

- **Control flow is deterministic** — the orchestrator is the LangGraph graph itself (conditional edges), **not an LLM**. Same day → same routing → reproducible + auditable. LLMs only reason at the leaf nodes (query-gen, research, PM, risk-narrative, reporting).
- **State object** (`FirmState`) threads through every node: tick metadata, query attempts + critiques, retrieved chunks, research view, proposal + thesis_card, engine result, risk assessment, approval result, fill, monitoring state, and accumulated **trace span ids**.
- **Retrieval retry reasons** — the relevance grader emits `{relevant, coverage, missing, failure_kind ∈ NO_HITS|WRONG_ENTITY|STALE|TOO_GENERIC|OFF_TOPIC, fix_hint}`. Query-gen maps `failure_kind` → strategy (broaden/step-back / tighten filter / adjust date-window / decompose / HyDE) and reformulates, never reusing a `prior_attempt`. Bounded to **2 retries**; on exhaustion → `INSUFFICIENT_EVIDENCE` (honest refusal, no trade). **The loop only fires on bad *retrieval*, never on a negative *decision*.**
- **Checkpointing:** `SqliteSaver` persists `FirmState` at every node. The `interrupt()` before each buy means **graph state survives the wait** and a process restart.
- **Partial failure:** each node wrapped in try/except → typed `NodeError` to trace; graph routes to a `degrade` path (skip ticker / abort cycle cleanly) rather than crashing the firm. Trade idempotency keys prevent double-execution on resume.
- **Everything is traced:** every node entry/exit, every query attempt + grader critique, every retrieved chunk set, the engine decision, the human decision, the fill, and each monitoring evaluation emit a span — the full causal chain of a trade is replayable from the trace alone.

### Pipeline Mechanics — the retrieval reasoning loop (CRAG)

The retrieve step is **corrective**: planning and grading are separated so retries are deliberate, not blind repeats.

1. **Query-Gen** produces a `QueryPlan` (baseline strategy on first pass).
2. **Retriever** (deterministic) runs the plan against Chroma with the time-box filter.
3. **Relevance Grader** (cheap Haiku critic) scores the chunks and, on failure, emits a **structured critique** — *why* it failed + a fix hint. This critique is the reasoning signal.
4. **Query-Gen reformulates** from the critique's `failure_kind`:

   | failure_kind | corrective reasoning |
   |---|---|
   | `NO_HITS` | broaden / step-back to a more general question |
   | `WRONG_ENTITY` | tighten ticker/entity filter + disambiguate |
   | `STALE` | adjust the date-window filter (data exists, filtered wrong) |
   | `TOO_GENERIC` | decompose into sub-questions, retrieve each |
   | `OFF_TOPIC` | HyDE — embed a hypothetical ideal answer, search by it |

5. **Termination:** relevant → Research; or budget (2) exhausted → `INSUFFICIENT_EVIDENCE` → `NoTrade`. Refusal over hallucination — the brief's "refuse/escalate when evidence is insufficient."

Each attempt (`query`, `strategy`, `critique`, `chunk_ids`) is written to the trace, so the demo can show *"attempt 1 STALE → widened date window → attempt 2 succeeded."*

## Trigger & Replay-Clock Mechanics

The firm does not trade live — it **replays a historical trading day**. The replay clock is the deterministic conductor: it advances simulated time, enforces lookahead-safety, and decides — via a deterministic **Dispatcher** — *which* pipeline path (if any) each tick runs. Nothing fires on its own; the clock wakes the agents only when there is a real reason.

### The clock

- Steps from market **open (09:30 ET) to close (16:00 ET)** in a configurable interval — **default hourly** (~7 ticks); the operator may choose a finer/coarser step.
- At each tick, `as_of = now`. **`as_of` is injected into every agent's context** so reasoning is time-aware (early session vs near-close reads differently).
- **Lookahead-safety:** the retriever and price feed are hard-filtered to `≤ as_of`. It is structurally impossible for an agent to see a doc published after `now` or a future price. This is enforced in code, not prompts.

### Active pool (sliding window)

The corpus is time-sorted by `published_date`. At each tick the **active pool** = docs with `as_of − lookback ≤ published_date ≤ as_of` (**default lookback 7 days** news + latest filings; refinable). As the clock advances, newly-eligible docs enter the pool automatically. **New-since-last-step** = docs in `(last_step, as_of]` — the signal the Dispatcher watches. A per-ticker `processed_doc_ids` set deduplicates so the same doc is never re-researched.

### Context is always on (deterministic Context Assembler)

Every tick carries the full accumulated context — not just the close. A deterministic **Context Assembler** (a function, *not* an agent) builds the fresh context window each tick from:

```
context = TickerMemory (structured, carried forward)
        + new delta (docs/price since last step, deduped)
        + as_of timestamp
        + portfolio snapshot (cash, position, cost basis)
        + EOD flag (set only at the pre-close tick)
```

`TickerMemory` per ticker — persisted as its **own append-only, versioned table** (one row per tick, never overwritten; see Data Model), so the firm's evolving beliefs are a queryable, replayable time series rather than an opaque blob. The Context Assembler reads the latest row; the dashboard/trace replay the full sequence. Resolves the "agent memory within a day" gap:

```
TickerMemory {
  ticker,
  current_view: ResearchView,        # last thesis + citations + as_of
  processed_doc_ids: set,            # dedup guard — never re-research a doc
  last_decision_price,               # price-move delta baseline
  position: {qty, cost_basis},       # how much is invested
  open_thesis: str,                  # why we hold / why we passed
  decision_log: [ {tick, action, reason} ]   # bounded
}
```

This stays compact **by structure** (fields are updated/overwritten, not appended as raw history), so no LLM compaction step is needed — assembly is templating, fully reproducible, zero extra tokens. The agents' own structured outputs (`open_thesis`, `key_points`, `decision_log`) *are* the running summary. (Seam: if scaled to many tickers / multi-day, add LLM summarization into the Research/PM output — not a new agent.)

### The Dispatcher (deterministic) — which path runs

At each tick the Dispatcher evaluates trigger conditions on facts only (no LLM, no judgment) and routes to exactly one path. Using an LLM here would pay tokens every hour merely to decide whether to spend tokens — self-defeating and non-reproducible.

```
each tick:
  advance clock → as_of = now
  refresh active pool (sliding window ≤ as_of)
  assemble context (Context Assembler)
  DISPATCH (deterministic, first match wins):
    pre-close scheduled tick?                              → DAY_REVIEW
    open / first tick?                                     → CONTEXT_BUILD
    new docs in (last_step, as_of] for a watched ticker?   → INCREMENTAL_NEWS
    |Δprice since last_decision_price| ≥ threshold?        → PRICE_REEVAL
    held position past stop / target?                      → MONITOR_SELL
    else                                                   → SKIP (snapshot only)
  run path → update TickerMemory → trace the tick (incl. SKIP + reason)
```

Defaults: price-move threshold **±2%** (operator-configurable); scheduled deep passes = **open + pre-close** only (midday optional, off by default).

### The six paths

| Trigger | Path | Pipeline | Retrieval |
|---|---|---|---|
| Open / first tick (cold start) | **CONTEXT_BUILD** | query-gen → CRAG → research → seed views across watched universe | cold, full, broad |
| New article/filing intraday | **INCREMENTAL_NEWS** | push new doc → Research (with carried context) → PM → Risk → … | the new doc only (skip query-gen/CRAG) |
| Price move ≥ threshold, no new news | **PRICE_REEVAL** | existing `current_view` + new price → PM → Risk → … | none (reuse view) |
| Held position hits stop/target | **MONITOR_SELL** | protective sell = deterministic; discretionary = re-enter PM | none |
| Pre-close scheduled tick | **DAY_REVIEW** | load full day context → **delta-retrieve** (dedup) for late docs → decision node with **EOD framing** → report | delta only |
| Nothing changed | **SKIP** | record a P&L snapshot, no agents | none — **zero tokens** |

- **CONTEXT_BUILD vs DAY_REVIEW** are the two *proactive, whole-universe/portfolio* passes; the rest are *reactive and narrow*. Open is cold (no prior context exists). Close is context-rich: it **builds on every decision made during the day** plus a delta-fetch for anything published since the last tick, and injects an **end-of-day framing** into the decision node — *"market closes in N minutes; you cannot act overnight; for each position decide hold / trim / flatten / rebalance given gap risk"* — then generates the daily report.
- **SKIP is a feature, not a no-op:** it still emits a trace span (e.g. *"11:00 SKIP — no new evidence, price +0.3%"*), so the demo shows the firm *deciding not to act* — discipline made observable, and the core of the cost-awareness story.

### Determinism & demo

Because the day is a **frozen replay**, the data-arrival timeline is fully controlled and the Dispatcher's routing is reproducible: same date → same sequence of ticks, paths, and triggers, every run. Pick a demo day with a well-timed news item so a live run visibly fires an `INCREMENTAL_NEWS` cycle mid-morning. Every tick — including SKIPs and the path chosen + why — is traced.

## Data Model

Two stores. **Relational state** in **SQLite via SQLAlchemy** (ACID, zero-ops, file-based, commits to repo; production path = swap to Postgres behind the same ORM). **Vectors** in **Chroma** (persistent, local, no service). LangGraph checkpoints in their own SQLite file.

Entities (relational):

```
Ticker          (symbol PK, name, added_at, data_start, data_end, source)
Portfolio       (id PK, cash, currency, created_at, updated_at)          1
Position        (id PK, portfolio_id FK, ticker FK, quantity, avg_cost_basis,
                 realized_pnl, updated_at)                                N per Portfolio
Trade           (id PK, ticker FK, side, quantity, status, est_notional,
                 proposed_price, fill_price, slippage, commission,
                 rationale, research_ref, risk_decision, idempotency_key,
                 created_at, filled_at)                                   N
ApprovalRequest (id PK, trade_id FK, reason, threshold_breached, status,
                 decision, edited_payload, decided_by, created_at,
                 decided_at)                                             1 per over-threshold Trade
PnLSnapshot     (id PK, ts, total_equity, cash, holdings_value,
                 spy_value, vs_spy_bps)                                   N (time series)
TickerMemory    (id PK, run_id FK, ticker FK, tick_seq, as_of,
                 stance, confidence, current_view_json, open_thesis,
                 position_qty, cost_basis, last_decision_price,
                 processed_doc_ids_json, decision_log_json,
                 dispatch_path, created_at)                               N (append-only, versioned)
                 -- ONE ROW PER (run, ticker, tick). Latest row = current memory
                 --   (read by the Context Assembler). Full set = the belief
                 --   timeline the dashboard/trace replay to show evolution.
Document        (id PK, ticker FK, type, source, source_url,
                 published_date, ingested_at, content_hash)              N per Ticker
Chunk           (id PK, document_id FK, ordinal, text, token_count)      N per Document
                 -- embedding vector stored in Chroma keyed by Chunk.id
Run             (id PK, kind, replay_date, started_at, ended_at, status) N  -- full-day id
Span            (id PK, run_id FK, parent_span_id FK, tick_seq, as_of,
                 kind, name, agent, tool, ticker?, trade_id?,
                 input_json, output_json, model?, prompt_tokens,
                 completion_tokens, cost_usd, latency_ms, cache_hit?,
                 status, error, started_at, ended_at)                    N per Run
                 -- kind ∈ TICK|AGENT|LLM|TOOL|RETRIEVAL_ATTEMPT|GUARDRAIL|
                 --        HITL|EXECUTION|EVENT
                 -- status ∈ OK|ERROR|REJECTED|SKIPPED|PENDING
                 -- id hierarchy: run_id (day) → tick_seq (tick) → id (action)
                 -- written on start (PENDING) + updated on completion → crash-durable
```

Relationships: `Portfolio 1—N Position`; `Ticker 1—N Trade/Document/TickerMemory`; `Trade 1—1 ApprovalRequest` (optional); `Document 1—N Chunk`; `Run 1—N Span/TickerMemory` (Span self-references parent → span tree per trade). `Trade.idempotency_key` unique → safe resume. `TickerMemory` is **append-only** (`unique(run_id, ticker, tick_seq)`): the firm's evolving beliefs are an auditable time series, never overwritten — the Context Assembler reads `max(tick_seq)` per ticker while the UI replays the full sequence.

**Crash reconciliation:** every book mutation (fill) is one DB transaction writing Trade + Position + PnLSnapshot atomically. On restart, the orchestrator: (1) loads LangGraph checkpoint, (2) reconciles any Trade in `APPROVED` but not `FILLED` via idempotency key, (3) recomputes equity from positions to verify invariant `cash + Σ holdings = equity`.

## API Boundaries

FastAPI. Public = consumed by React UI; internal = orchestrator↔stores (in-process, not HTTP).

| Method/Path | Responsibility | Consumer |
|---|---|---|
| `GET /portfolio` | cash, equity, holdings, today P&L vs SPY | UI: Portfolio |
| `GET /positions` | open positions w/ cost basis + unrealized P&L | UI: Portfolio |
| `GET /trades` / `GET /trades/{id}` | trade list / single trade w/ rationale + refs | UI |
| `GET /tickers/{symbol}/memory?run_id` | **belief timeline** — TickerMemory rows per tick (stance/confidence/thesis evolving) | UI: belief evolution view |
| `GET /pnl/history?from&to` | equity & vs-SPY time series | UI: chart |
| `GET /tickers` | universe (default + ingested) | UI |
| `POST /tickers` `{symbol}` | **ingest**: fetch prices + corpus, embed, persist; returns job status | UI: ticker search |
| `GET /tickers/{symbol}/status` | ingestion progress | UI |
| `GET /approvals?status=pending` | pending Risk Committee items | UI: Approvals |
| `POST /approvals/{trade_id}/decide` `{decision, edits?, approver}` | approve/edit/reject → **resumes** the paused graph | UI: Approvals |
| `POST /run/replay` `{date, tickers[]}` | trigger a trading-day replay for an operator-chosen date + ticker set | UI / CLI / eval |
| `GET /runs/{id}/feed` | time-ordered event feed (spans) — primary observability view; supports `?ticker`/`?trade_id` filters | UI: Event Feed |
| `GET /runs/{id}/trace` / `GET /trades/{id}/trace` | same spans re-grouped into the causal tree of one trade | UI: Trace Viewer, reviewer |
| `GET /runs/{id}/export` | download full feed as JSONL (+ rendered `decision_log.md`) | UI: Export button, reviewer |
| `POST /admin/reset` `{scope: traces\|all}` | clear trace store (and optionally portfolio state) to start fresh | UI: Reset button (confirm-gated) |
| `GET /reports/{date}` / `GET /reports/{date}.xlsx` | daily report JSON / Excel download | UI, reviewer |
| `WS /stream` (or SSE) | live event stream; feed re-hydrates from store on (re)connect | UI: live Event Feed |
| `GET /health` | liveness + state-invariant check | ops/CI |

## Auth Strategy

**V1: no auth** — single-operator local demo; not multi-tenant. The one security-sensitive action (approval) is gated by an `approver` field captured for the audit log. **Production seam:** a FastAPI dependency (`require_api_key`) is stubbed on write endpoints (`POST /tickers`, `/approvals/decide`, `/run/replay`) so adding API-key/OAuth is a one-file change without touching handlers. Authorization model documented as future RBAC (roles: operator, risk-committee, viewer). Called out explicitly in the runbook as a known production gap — honesty over pretending it's done.

## Guardrails (priority pillar)

Framed by **threat model** — what can go wrong in an AI firm that touches money and reads untrusted text, and what stops each. Defense-in-depth; the unbypassable layers are **code, not prompts**.

| # | Threat | Guardrail | Type | On failure |
|---|---|---|---|---|
| 1 | Garbage/malformed input reaches an LLM | Input validation | deterministic | reject |
| 2 | LLM output wrong-shaped **or insane-valued** | Schema + semantic validation | deterministic | bounded retry → typed fail |
| 3 | LLM invents numbers/dates/quotes | Citation + **numeric-consistency** verifier | deterministic | strip claim / force `INSUFFICIENT_EVIDENCE` |
| 4 | Retrieved news/filing hijacks an agent | Injection defense + tool isolation | hybrid | quarantine chunk |
| 5 | LLM proposes a trade that breaks limits | Risk engine | deterministic | hard `REJECT` |
| 6 | Big/irreversible action, no oversight | HITL gate | deterministic | pause for human |
| 7 | Runaway cost / infinite loops | Resource circuit-breaker | deterministic | halt run, partial report |
| 8 | Future data leaks into a decision | Lookahead-integrity assertion | deterministic | abort run, loud trace |

1. **Input validation** — Pydantic models on every agent boundary + every API request. Reject malformed before it reaches an LLM.
2. **Output schema + semantic validation** — all LLM outputs parsed into Pydantic (Anthropic tool/structured output); parse failure → bounded retry with the validation error → typed failure. **Beyond shape, field validators enforce sanity:** `quantity > 0`, `confidence ∈ [0,1]`, `side ∈ {BUY,SELL}`, `est_notional ≤ equity`, stance ∈ enum. Shape-valid ≠ sane — both must hold before any value flows downstream.
3. **Citation + numeric-consistency check** — deterministic verifier after Research/PM: every non-neutral stance and **every numeric claim** must map to a `citation.chunk_id` in the retrieved set, **and the cited number/quote must literally appear in that chunk's text** (regex/substring match). This catches the worst failure — a *real* citation attached to a *fabricated* number. Any uncited or unsupported claim → stripped, or the view is forced to `INSUFFICIENT_EVIDENCE`. This is what makes "no hallucinated numbers/dates/quotes" real.
4. **Prompt-injection defense** (web/corpus text is untrusted) — retrieved text is wrapped in clearly delimited data blocks with spotlighting; system prompt instructs the model to treat it as data, never instructions; a lightweight injection-pattern classifier flags chunks containing imperative/tool-directive language ("ignore previous", "transfer", "buy now") → quarantined, not fed downstream. Agents that touch untrusted text have **no execution tools** (only the deterministic broker executes).
5. **Hard trading limits — the Risk Engine** — deterministic module evaluated on every proposal *and re-checked immediately before fill*. Limits (configurable, safe defaults): max position % of equity, max single-order notional, max daily loss (kill-switch halts trading), max trades/day, no shorting beyond holdings, market-hours-only. A **hard** breach is `REJECT` and the LLM **cannot override it** — the engine is the gate to the book. This is the brief's "trading limits the system cannot exceed."
6. **HITL gate** — **every buy** `interrupt()`s and waits; nothing is purchased without a recorded human decision. The human sees the `thesis_card`: headline, why-now, expected edge, risks, confidence, and the **cited evidence** behind every claim — informed, auditable judgement, not a rubber stamp. Illegal trades are hard-rejected by the engine before reaching the human.
7. **Resource circuit-breaker** — per-run budget the system cannot exceed: max LLM calls, max tokens, max wall-clock. On breach → halt the run cleanly, write a `BUDGET_EXCEEDED` trace span, emit the partial report. Bounds runaway loops/cost and directly answers the brief's "token consumption" concern. *(Build note: measure a normal run first, then set limits; track via a GitHub issue at repo time.)*
8. **Lookahead-integrity assertion** — time-boxing is enforced **two independent ways**: (a) the retriever filters retrieval to `published_date ≤ as_of`, and (b) an independent **boundary assertion** verifies that *no chunk with `published_date > as_of` enters ANY agent's context on ANY path* — including the paths that bypass the retriever (`INCREMENTAL_NEWS` direct-push, `PRICE_REEVAL` reusing cached views). A violation **aborts the run** with a `LOOKAHEAD_VIOLATION` trace rather than silently corrupting results. Makes lookahead bias impossible *by construction and provable*, not merely intended.

**Measuring effectiveness (→ Eval Harness):** a red-team slice of the golden dataset seeds **injected docs** (jailbreak/instruction-override text) and **over-limit / illegal proposals**; the eval reports **block-rate** (% injections quarantined, % illegal trades rejected, % hallucinated numbers caught). Converts "we have guardrails" into "guardrails are N% effective on M adversarial cases, measured in CI" — and earns the "documented prompt-injection defenses" bonus.

## Observability (priority pillar)

Goal from brief: *replay one trade end-to-end from the trace alone.* The primary surface is a **live, persistent event feed** — a time-ordered stream of every action the firm takes, with every model's input/output inspectable.

### The event feed (primary view)

A chronological feed down a time axis. Each action the firm takes is one **event** that posts to the feed as it happens:

```
RUN 2024-05-23 (full-day id: run_8f3a)
├─ 09:30  TICK · CONTEXT_BUILD · "market open"
│   ├─ Query-Gen        working… → done · 4 queries        [▸ show queries]
│   ├─ Retrieve         → 11 chunks
│   ├─ Relevance-Critic working… → done · relevant (cov 0.82)
│   ├─ Research (NVDA)  working… → done · BULLISH 0.7 · in 1,240 / out 380 tok  [▸ show output]
│   ├─ Guardrail        citation+numeric ✓ · injection ✓
│   ├─ PM               working… → done · BUY 50 NVDA                          [▸ show output]
│   ├─ Risk Engine      ✓ legal  · Risk Agent → REQUIRE_HUMAN
│   ├─ HITL             ⏸ awaiting approval → APPROVED by mark (waited 38s)
│   └─ Execution        FILLED 50 @ 924.10 (slippage 0.04%, commission $1)
├─ 10:30  TICK · SKIP · "no new evidence, price +0.3%"
├─ 11:30  TICK · INCREMENTAL_NEWS · "NVDA 8-K published 11:12"
│   └─ …
```

- **Per event:** who acted, `working…/done` status, **duration**, **tokens in/out**, result summary, and an **expandable raw model output (collapsed by default)** the reviewer opens on demand.
- **Every tick is an event — including `SKIP`** (shows the firm *deciding not to act* + why) and terminal states (`INSUFFICIENT_EVIDENCE`, `BUDGET_EXCEEDED`, `LOOKAHEAD_VIOLATION`, `NODE_ERROR`).
- **Live + re-hydrating:** new events stream over `WS /stream` as they occur; on a page reload or server restart the feed **rebuilds from the store** (it is never held only in memory).

### Three-level ID hierarchy

Everything is addressable so the feed survives restarts and can be exported/filtered:

| Level | Your term | Field | Scope |
|---|---|---|---|
| **Run** | full-day id | `run_id` | one replayed day |
| **Tick** | timestamp id | `tick_id` (`tick_seq` + `as_of`) | one clock step |
| **Action** | action id | `span_id` (+ `parent_span_id`) | one call/agent/guardrail step |

`run_id → tick_id → span_id`. Each span also carries `ticker?`, `trade_id?`, `status`, so the feed can be filtered to one ticker or one trade, or re-grouped into the causal tree of a single trade when needed (secondary view).

### Persistence & durability

- **Spans are written to SQLite the moment they start and updated on completion** — durable through website restart *and* server crash. The feed always reflects the store, never volatile memory.
- **Span fields:** `span_id, run_id, parent_span_id, tick_seq, as_of, kind, agent/tool, ticker?, trade_id?, status, input_json, output_json, model?, prompt_tokens, completion_tokens, cost_usd, latency_ms, cache_hit?, error?, started_at, ended_at` (see Data Model).
- OTel-compatible (`trace_id = run_id`, `span_id`, `parent_span_id`) so it *could* export to Jaeger/LangSmith in prod (seam, not required for V1).

### Controls

- **Export** — `GET /runs/{id}/export` downloads the full feed as **JSONL** (+ rendered `decision_log.md`); the committed sample run ships this artifact.
- **Reset / start fresh** — `POST /admin/reset` clears the trace store (and optionally portfolio state) so a demo can begin clean. Guarded by a confirm in the UI.

### Other views (built on the same spans)

- **Belief-evolution** — the append-only `TickerMemory` series replayed per ticker (stance/confidence/thesis tick by tick, e.g. *09:30 NEUTRAL 0.4 → 11:00 after news BULLISH 0.7*) — the agents' evolving thought process made visible.
- **Cost view** — tokens and `$` rolled up per run / per agent / per tick (token-consumption + cost-routing story).
- **Replay-from-trace contract:** the feed for one trade must answer, with no re-run — (1) what triggered it, (2) what evidence (every retrieval attempt + chunk_ids + grader verdict), (3) each agent's typed in/out, (4) why this size/side, (5) every guardrail verdict, (6) the human decision + any edits, (7) the fill, (8) the cost. If it can't, the trace is incomplete.

### Structured logs

`structlog` JSON logs, correlated by `run_id`/`tick_id`/`span_id`, mirror the feed for grep/CI.

## LLM Routing (cost-aware — bonus)

Single `LLMRouter` abstraction over Anthropic. **Default `claude-haiku-4-5`** for high-volume cheap calls (Research retrieval-grounding, Reporting); **escalate to `claude-sonnet-4-6`** for the harder reasoning (PM trade decision, Risk explanation). Provider is interface-abstracted so a **local model / recorded-cassette provider** swaps in for offline CI. Per-call cost recorded in spans. This gives the cost-aware-routing bonus cheaply and addresses the "token consumption" evaluation note.

## Eval Harness

Reproducible historical replay, runnable in CI, **zero token spend**:
- **Determinism:** frozen market snapshot (parquet, committed) + frozen time-boxed corpus + **recorded LLM responses** (cassette per agent call, keyed by prompt hash). CI replays cassettes → no key, no cost, deterministic.
- **Return metrics:** end-of-day P&L, return %, vs-SPY (alpha), max drawdown, # trades, turnover.
- **Process metrics (the differentiator):** groundedness rate (% claims with valid citations), citation validity (quote substring match), refusal correctness (did it refuse when evidence absent — on seeded no-evidence cases), guardrail effectiveness (% injected/over-limit attempts blocked — seeded adversarial cases), schema-valid rate, HITL trigger correctness, mean cost/run.
- **Output:** `docs/eval-report.md` + committed JSON. CI job fails if process metrics regress below thresholds.

## Infrastructure Decisions

- **Packaging:** Python 3.12, `pyproject.toml` (uv/pip). Backend + agents one package; React app separate.
- **Containers:** `Dockerfile` (backend, serves built React static) + `docker-compose.yml` (backend + volumes for SQLite/Chroma/artifacts). `clone → docker compose up → seeded demo` in <10 min.
- **CI:** GitHub Actions — lint, unit tests, **eval harness on cassettes**, build image. (IaC/CD beyond this = noted bonus, not V1.)
- **Observability stack:** self-contained (SQLite spans + JSONL + structlog); OTLP export seam for prod.
- **External services:** only at **ingest time** (yfinance prices, SEC EDGAR filings, news). Runtime/replay is fully offline. No external dependency in the demo path.
- **Secrets:** `.env` (Anthropic key, optional Voyage key). CI needs neither (cassettes + local embeddings).

## Key Tradeoffs

- **SQLite over Postgres** — optimized for zero-ops + commit-to-repo + crash-recovery demo; sacrificed concurrent-write scale (acceptable: single-process firm; ORM keeps Postgres a swap).
- **Replay over live trading** — optimized for reproducibility + deterministic eval + no lookahead; sacrificed "real-time" realism (the brief explicitly wants reproducible historical replay, so this is aligned).
- **Deterministic risk engine over LLM-judged risk** — optimized for safety (unbypassable limits); sacrificed some nuance (LLM still *explains*, engine *enforces*). Correct trade for money-touching code.
- **Cassette-based eval over live LLM eval** — optimized for CI determinism + zero cost; sacrificed catching live model drift (note: a separate non-CI "live smoke" run covers that).
- **FastAPI+React over Streamlit** — optimized for a polished, convincing demo (your call); cost is real frontend time — mitigated by scoping UI to 3 screens and keeping agents the priority.
- **5 agents over fewer** — matches real desk roles + the "≥4 agents" bar with clear separation; cost is more orchestration surface — mitigated by uniform typed-contract pattern.
- **Voyage embeddings, local fallback** — Voyage for corpus/query quality; `bge-small` fallback keeps CI offline/$0. Vectors persisted once → CI never re-embeds.
- **HITL on every buy** — optimized for trust/auditability/explainability (the demo's credibility moment); cost is a human click per buy — acceptable and intended.

## Resolved Decisions (was Open Questions)

- **User chooses time + stocks** — the operator picks the **replay date** and **which tickers** the firm trades for a run; tickers outside the default set are ingested on demand (prices + corpus + Voyage embeddings) and persisted. `POST /run/replay {date, tickers[]}`, `POST /tickers {symbol}`.
- **HITL = every buy, always** — no silent auto-buy. Each BUY pauses with a `thesis_card` (why-now, expected edge, risks, confidence) where **every claim is backed by a cited corpus source**. The engine hard-rejects illegal trades before they reach the human. Risk-reducing sells may auto-approve. Thresholds (max-position 10% equity, max-order $25k, max-daily-loss 3%) are the **hard** engine limits; confirm values before eval.
- **Embeddings = Voyage** (`voyage-3.5`), local fallback for CI.
- **Output channels = dashboard + Excel** (no Slack). Dashboard = live/interactive (incl. live agent-stage stream); Excel = portable, committed, auditable artifact. Satisfies the brief's ≥2-channel requirement.
- **Event triggers = in V1.** Two trigger kinds: **scheduled ticks** (open / midday / pre-close) and **event triggers** (a corpus news item or a price move kicks off a cycle). Separately, the dashboard streams **which agent is active / what stage** live via `WS /stream` — that's observability, not a trigger.

## Open Questions

- **Sample replay day** — specific historical date, chosen later; must have real citable news for ≥1 ticker so the demo trade is compelling. *Resolver: you, at corpus build.*

---
*ADRs: see `docs/adrs/`. Next pipeline step: `spec-write` per feature, then `sprint-plan`.*
