# PRD: The AI Investment Firm

> Multi-agent paper-trading system. Cato Networks "Agentic AI Engineer" home task.
> Priority order: **agentic system → guardrails → observability**. Everything else serves these.

## Problem Statement

A real investment desk is a chain of specialized humans (research, portfolio management, risk, execution, reporting) making stateful decisions under hard safety limits, leaving an audit trail. The task: prove an AI multi-agent system can run that whole desk for a trading day — believably, observably, auditably — with production-grade engineering. **Not** to beat the market; to demonstrate trustworthy, reliable, grounded agent automation.

## What we're being judged on (re-derived from the brief)

Graders are senior engineers. Weighting, highest first:

1. **Multi-agent design** — real role-based collaboration, typed contracts, defined failure modes.
2. **Production readiness** — persistent state (survives crash), HITL, observability, guardrails, evals.
3. **RAG groundedness** — citations, refusal when evidence insufficient, no hallucinated numbers.
4. **Eval rigor** — return AND process metrics, reported honestly.
5. **Code quality + architecture clarity + ability to defend trade-offs.**

V1 must be **excellent** on 1–3, **honest and present** on 4–5. We win by being *reliable and safe*, not flashy.

## Jobs-to-be-Done

| Segment | When… | I want to… | so I can… |
|---|---|---|---|
| **The Firm (autonomous)** | market events / scheduled ticks occur during the trading day | analyze evidence, decide trades, execute on a paper book, and report | run the desk end-to-end without a human in every step |
| **Risk Committee (human)** | a proposed trade exceeds configured risk thresholds | pause the system and approve / edit / reject the trade | keep ultimate control over high-impact decisions |
| **Reviewer / grader** | reviewing the submission | replay any trade end-to-end from traces, run the eval, read reports | trust the system is grounded, safe, and production-minded |
| **Operator (you, demo)** | running the live demo | add a new ticker, trigger a day replay, watch agents work, sign off a trade | showcase the full workflow convincingly |

## Audience Segments (detail)

- **Autonomous firm** — primary actor. Outcome metric: complete, grounded, guardrail-compliant trading day with persistent state.
- **Human Risk Committee** — single approval touchpoint. Outcome metric: every above-threshold trade pauses and waits; no large trade executes without sign-off.
- **Reviewer** — outcome metric: clone→demo <10 min; can replay a trade from trace alone; eval runs in CI.

No conflicting-needs scope risk — segments are sequential in one workflow.

---

## Story Map

### Activity A — Set up the world (data + corpus)
- **A1. Pre-load default universe**
  - As the operator, I want 3–5 tickers (AAPL, MSFT, NVDA, +SPY benchmark) pre-loaded with frozen price data and a grounded corpus, so the demo runs deterministically offline.
- **A2. On-demand ticker ingestion** *(your add)*
  - As the operator, I want to search a new ticker and have the system fetch its price history + build a corpus (filings/news), embed, and save it, so the firm's universe is extensible — not hardcoded.
  - As the operator, I want ingested tickers persisted, so they're available on the next run.
- **A3. Time-boxed corpus**
  - As the firm, I want the corpus filtered to documents dated ≤ replay date, so agents never see the future (no lookahead bias).

### Activity B — Trigger the desk
- **B1.** As the firm, I want scheduled ticks during market hours (e.g. open, mid-day, pre-close) to trigger a decision cycle.
- **B2.** As the firm, I want market events (price moves, fresh news in corpus) to trigger a cycle.

### Activity C — Analyze (Research agent)
- **C1.** As the Research agent, I want to retrieve evidence for a ticker from the vector store, so I form a view grounded in citable sources.
- **C2.** As the Research agent, when evidence is insufficient, I want to refuse/escalate rather than guess.
- **C3.** As the Research agent, I want typed output (thesis, direction, confidence, citations[]), so downstream agents consume it safely.

### Activity D — Decide (Portfolio Manager agent)
- **D1.** As the PM agent, I want to turn a research view + current portfolio into a concrete proposed trade (ticker, side, quantity/notional, rationale).
- **D2.** As the PM agent, I want to respect cash and position constraints when sizing.

### Activity E — Risk check + human gate (Risk agent + Committee)
- **E1.** As the Risk agent, I want to validate each proposed trade against hard limits (max position %, max order notional, max daily loss, etc.).
- **E2.** As the Risk agent, I want to auto-approve trades under threshold and **pause** trades over threshold for human review.
- **E3.** As the Risk Committee (human), I want to approve / edit / reject a paused trade in the UI, with graph state persisting across the wait.
- **E4.** As the firm, I want hard limits the system *cannot* exceed even if an agent tries (enforced in code, not prompts).

### Activity F — Execute (Execution agent)
- **F1.** As the Execution agent, I want to simulate a realistic fill (slippage + commission, respect market hours) and update the book.
- **F2.** As the firm, I want portfolio state (cash, holdings, cost basis, P&L) persisted transactionally after every fill.

### Activity G — Report (Reporting agent)
- **G1.** As the firm, I want an end-of-day report (positions, trades, P&L vs SPY, decisions + citations) via ≥2 channels.
- **G2.** As the reviewer, I want reports + trace artifacts committed to the repo for the sample run.

### Activity H — Observe + persist + recover
- **H1.** As the reviewer, I want a structured trace of every agent invocation, tool call, and trade — enough to replay one trade end-to-end.
- **H2.** As the firm, I want state to survive a restart and reconcile cleanly after a crash mid-cycle.

### Activity I — Evaluate
- **I1.** As the reviewer, I want a reproducible historical replay producing **return metrics** (vs SPY) and **process metrics** (groundedness, decision quality, guardrail effectiveness), runnable in CI.

---

## V1 Scope (SLC Slice)

**In scope — the spine, done well:**
- A1, A2, A3 (default universe + on-demand ingestion + time-boxing)
- B1 (scheduled ticks) — B2 event triggers if time allows
- C1–C3, D1–D2, E1–E4, F1–F2, G1–G2, H1–H2, I1 — **all core agent, guardrail, HITL, state, observability, eval stories are in V1**

**SLC rationale:** Simple = 4 agents + a thin React/FastAPI surface, one replayed day. Lovable = the live Risk Committee approval + replayable traces are the "wow." Complete = a full trading day runs end-to-end, grounded, guardrailed, evaluated, and persisted. This slice maps 1:1 to the grading criteria — we go deep where graders look, not wide.

### Out of scope for V1 (parked, mention in "next 3 things")
- Live (non-replay) market operation
- Multi-day backtests / portfolio optimization
- Email + Slack channels (ship dashboard + Excel; others are bonus)
- Cloud deployment, IaC, CI/CD pipeline (bonus — note the path)
- AWS Bedrock AgentCore / managed runtime (bonus)
- Cost-aware model routing beyond "cheap model default + escalate" (note as future)
- Auth / multi-user

## Parking Lot
- Streaming live news ingestion + prompt-injection red-team suite (mention defenses are designed in)
- Backtesting across a window with statistical significance
- Position-level risk analytics (VaR, beta, sector exposure)
- Model router with per-task cost/quality tiers
- Managed agent runtime migration (Bedrock AgentCore)

## Open Questions
- LLM provider + models: assume **Anthropic** (your key), cheap model default (Haiku-class) w/ escalation. Confirm in tech-design.
- Embeddings: **Voyage** (free tier) vs **local** (sentence-transformers) fallback — decide in tech-design (cost vs offline-CI).
- Replay data source: **yfinance** (free, no key) for prices vs **Alpaca** paper API — decide in tech-design.
- Exact threshold values for HITL (max position %, order notional) — set sane defaults, make configurable.
- Which historical day to commit as the sample run (pick one with real news in corpus for a compelling trade).
- 2nd output channel: **Excel/CSV** confirmed; Slack as stretch?

---

*Next step: `tech-design` — converts this into architecture (agent contracts, LangGraph flow, RAG design, state schema, API contracts, frontend design, observability + guardrail implementation, deployment view).*
