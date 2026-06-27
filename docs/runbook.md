# Runbook

How to operate the firm: run it, drive a trading day, approve trades, read the report,
audit the trace, and recover from a crash.

## Modes

- `LLM_MODE=cassette` (default) — no network, no keys. Agents replay recorded/stub
  responses. Used by tests and the eval harness. RAG uses an in-memory store + a
  deterministic fake embedder.
- `LLM_MODE=live` — calls Anthropic for agents and Voyage + Chroma for RAG. Requires
  `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY`. Missing keys fail loudly (no silent
  fallback to fakes).

Copy `server/.env.example` → `server/.env` and edit.

## 1. Offline, zero-config (fastest — no keys, no network)

```bash
cd server
pip install -e ".[dev]"           # add --trusted-host pypi.org --trusted-host files.pythonhosted.org on a walled network
python -m pytest -q               # full suite, deterministic
python -m eval.harness            # golden + red-team eval → docs/eval-report.md
```

Inspect the committed sample run under [`docs/sample-run/`](sample-run/) — report
(`.json`/`.xlsx`) plus the full span trace (`trace.jsonl`).

## 2. Full app (Docker)

```bash
docker compose up --build         # builds web, FastAPI serves it on :8000
open http://localhost:8000
```

SQLite + Chroma persist in the `firm-data` volume across restarts.

## 3. Full app (local dev)

```bash
# backend
cd server && pip install -e ".[dev]" && uvicorn app.main:app --reload --port 8000
# frontend (separate shell)
cd web && npm install && npm run build      # served by FastAPI at /
# or: npm run dev  for the Vite dev server with HMR
```

## Driving a trading day (UI)

1. **Datasets & Run** tab → enter a date (e.g. `2024-05-23`) and tickers (e.g. `NVDA`),
   **Ingest**. Prices come from yfinance; corpus from SEC EDGAR (both need network).
   `SPY` is always added as the benchmark.
2. **Run replay** on the ready day. The **Event Feed** streams every span live.
3. **Approvals** tab → the Risk Committee inbox. Every buy waits here; approve / edit
   qty / reject. Risk-reducing sells and protective stops execute automatically.
4. **Report** tab → end-of-day P&L vs SPY, holdings, decision log with citations;
   **Download .xlsx** for the second channel.
5. **Observability** tab → cost rollup, belief-evolution per ticker, **Export trace
   (JSONL)**, and **Reset store** (confirm-gated).

## API quick reference

| Action | Endpoint |
| --- | --- |
| Ingest a day | `POST /datasets {date, tickers}` |
| List ready days | `GET /datasets` |
| Run replay | `POST /run/replay {date, tickers}` |
| Live event stream | `WS /stream` · `GET /runs/{id}/feed` |
| Approvals inbox | `GET /approvals?status=PENDING` |
| Decide | `POST /approvals/{id}/decide {decision, approver, edited_quantity}` |
| Report | `GET /runs/{id}/report` · `GET /runs/{id}/report.xlsx` |
| Belief timeline | `GET /runs/{id}/tickers/{sym}/memory` |
| Cost rollup | `GET /runs/{id}/cost` |
| Export trace | `GET /runs/{id}/export` |
| Reset store | `POST /admin/reset {confirm: true}` |

## Crash recovery

On boot the server reconciles any `APPROVED`-but-unfilled trade by re-driving it
through the broker with the approval id as the idempotency key (a fill that already
happened replays as a no-op — never a double-fill), then verifies the ledger invariant
(`stored cash/shares == reconstructed from FILLED trades`). If anything was fixed or the
book is off, a `crash_recovery` span records it. Kill the process mid-cycle and restart
to see it run.

## Determinism & safety knobs (`server/app/config.py`)

`price_move_threshold`, `act_confidence_threshold`, `max_position_pct`,
`max_order_notional`, `max_daily_loss_pct`, `max_trades_per_day`, `stop_loss_pct`,
`take_profit_pct`, `trim_fraction`, and the circuit-breaker budgets
(`max_llm_calls_per_run`, `max_tokens_per_run`, `max_run_seconds`). All overridable via
`.env`.

> **Budget limits are still first-pass guesses.** Measure a normal live run, then set
> real per-run call/token/time caps (tracked as a follow-up).
