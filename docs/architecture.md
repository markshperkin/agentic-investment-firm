# Architecture

Agentic investment firm that replays one trading day, tick by tick, over a fixed
news + price corpus. LLM agents make **judgments** (what's relevant, what the thesis
is, buy/sell/hold, exit bounds); deterministic code makes **math and enforcement**
decisions (retrieval routing, sizing, bound clamping, exit triggers, execution).

The day is sliced into ticks (hourly by default, `tick_interval_minutes`). On each tick
a **deterministic dispatcher** picks exactly one path per ticker. Only the open and the
incremental-news paths run fresh research; everything else is cheaper by design.

---

## 1. Component layers

```mermaid
flowchart TB
  subgraph API["API / UI"]
    RUN["POST /run"]
    REP["GET /runs/:id/report[.xlsx]"]
    HITLAPI["HITL approve/edit/reject"]
    FEED["Event feed (SSE spans)"]
  end

  subgraph ORCH["Orchestration (firm/)"]
    RUNNER["runner: day loop"]
    CLOCK["clock: ticks"]
    DISP["dispatcher: first-match-wins"]
    PIPE["pipeline: research to execution"]
    MON["monitor: stop/target + day_review"]
    HITLM["hitl: approval gate"]
    MEM["memory: ticker timeline"]
  end

  subgraph AGENTS["LLM agents (agents/)"]
    QG["query_gen"]
    RC["relevance_critic"]
    RES["research"]
    PM["pm (+exit bounds)"]
    RISKA["risk (narration)"]
    DR["day_review"]
    RPT["reporting"]
  end

  subgraph RAGL["RAG (rag/)"]
    CRAG["crag loop"]
    RET["retriever (+injection scan)"]
    VS["vector_store / embeddings"]
  end

  subgraph DET["Deterministic core"]
    RE["risk_engine"]
    SIZ["sizing"]
    CLAMP["clamp_bounds"]
    BROK["paper broker"]
    PORT["portfolio / positions"]
  end

  subgraph GUARD["Cross-cutting guardrails"]
    BUD["budget circuit-breaker"]
    CIT["citations"]
    LA["lookahead assert"]
  end

  RUN --> RUNNER --> CLOCK --> DISP --> PIPE
  DISP --> MON
  PIPE --> CRAG --> RET --> VS
  CRAG --> QG & RC
  PIPE --> RES --> PM --> RE
  PM --> CLAMP
  RE -->|AUTO_APPROVE| BROK
  RE -->|REQUIRE_HUMAN| HITLM --> HITLAPI
  HITLM --> BROK
  MON --> DR
  MON --> BROK
  BROK --> PORT
  PIPE --> MEM
  REP --> RPT
  AGENTS -.budget.-> BUD
  RES -.-> CIT
  RET -.-> LA
```

---

## 2. The daily loop + dispatcher (every tick)

`runner._run_ticks` walks each tick, gathers three signals (price move, new docs,
stop/target triggers), and asks the dispatcher for the path. **First match wins; one
path per tick.**

```mermaid
flowchart TD
  T["Tick i of N"] --> S["Gather signals:<br/>max_abs_move, new_docs?, stop_triggers?"]
  S --> D{"dispatcher.decide<br/>(first-match-wins)"}
  D -->|"i == 0"| CB["CONTEXT_BUILD<br/>(market open)"]
  D -->|"i == N-1"| DRV["DAY_REVIEW<br/>(pre-close)"]
  D -->|"new filing"| IN["INCREMENTAL_NEWS"]
  D -->|"move >= threshold"| PR["PRICE_REEVAL"]
  D -->|"stop/target hit"| MS["MONITOR_SELL"]
  D -->|"else"| SK["SKIP (no-op)"]
```

Priority matters: at the **last** tick it is always `DAY_REVIEW` even if a filing also
landed; a stop/target only fires when nothing higher-priority did. `CONTEXT_BUILD` and
`DAY_REVIEW` fan out to **all** tickers; `INCREMENTAL_NEWS`/`PRICE_REEVAL`/`MONITOR_SELL`
only touch the affected tickers.

| Path | Trigger | Research? | LLM? | Outcome |
|---|---|---|---|---|
| `CONTEXT_BUILD` | tick 0 | full CRAG | yes | open thesis → maybe trade |
| `INCREMENTAL_NEWS` | new filing | new docs only | yes | revise thesis → maybe trade |
| `PRICE_REEVAL` | move ≥ 2% | reuse cached view | PM only | re-decide vs new price |
| `MONITOR_SELL` | price crosses stop/target | none | **no** | deterministic protective sell |
| `DAY_REVIEW` | last tick | delta evidence | day_review | HOLD / TRIM / FLATTEN |
| `SKIP` | no signal | none | no | nothing |

---

## 3. Shared sub-flow: PM → bounds → risk → execution

`CONTEXT_BUILD`, `INCREMENTAL_NEWS`, and `PRICE_REEVAL` all converge on
`_pm_risk_route → _risk_and_route`. This is where the **per-position exit bounds** are
born and where the human gate lives.

```mermaid
flowchart TD
  V["Research view<br/>(stance, confidence)"] --> G{"actionable?<br/>stance ok &amp; conf >= 0.6"}
  G -->|no| NT["NoTrade → remember"]
  G -->|yes| PMD["PM decides BUY/SELL/HOLD<br/>+ stop_loss_pct, take_profit_pct"]
  PMD -->|HOLD| NT
  PMD -->|BUY/SELL| CL["clamp_bounds<br/>stop ≤ 4%, target ≤ 10%"]
  CL --> SZ["position_sizer<br/>(confidence × equity, cash-capped)"]
  SZ -->|qty <= 0| NT
  SZ --> PROP["TradeProposal<br/>(qty, notional, bounds)"]
  PROP --> RE{"risk_engine.evaluate"}
  RE -->|"SELL → AUTO_APPROVE"| EX["broker.execute"]
  RE -->|"BUY &lt; $25k → AUTO_APPROVE"| EX
  RE -->|"BUY ≥ $25k → REQUIRE_HUMAN"| H["submit_for_approval<br/>(carries bounds)"]
  H -->|blocking replay| PAUSE["run PAUSES<br/>until decision / timeout"]
  H -->|async eval/CI| Q["queue + continue"]
  PAUSE --> RES2{"approve / edit / reject"}
  RES2 -->|approve/edit| EX
  RES2 -->|reject/timeout| STOP["no fill"]
  EX -->|BUY fill| WB["write stop/target onto position"]
  EX --> PORT["portfolio updated"]
```

Notes:
- **Sizing is deterministic** — the PM never chooses quantity.
- **Bounds are clamped regardless of what the PM emits** (`clamp_bounds`: floor
  `min_bound_pct`, caps `max_stop_loss_pct` / `max_take_profit_pct`). The LLM proposes;
  code enforces.
- `risk_engine` has no policy REJECT: impossible fills (insufficient cash, oversell) are
  refused **physically** by the broker, not by a rule.
- The human-approval path persists bounds on the `ApprovalRequest` so the eventual fill
  still stamps them onto the position.

---

## 4. Exit-bounds lifecycle (the new mechanism)

```mermaid
flowchart LR
  PM["PM picks stop/target %<br/>(sized to conviction)"] --> CLAMP["clamp to 0.5%..4% / 0.5%..10%"]
  CLAMP --> POS["stored on Position<br/>(stop_loss_pct, take_profit_pct)"]
  POS --> TICK["every later tick:<br/>stop_triggers scans price vs basis"]
  TICK -->|"price ≤ basis × (1 - stop)"| SL["STOP_LOSS → full exit"]
  TICK -->|"price ≥ basis × (1 + target)"| TP["TAKE_PROFIT → full exit"]
  TICK -->|"inside the band"| HOLDB["no action"]
```

- Bounds are set **at the BUY fill** and persisted per position; fallback to config
  defaults if a position somehow carries none.
- Enforcement is the deterministic `MONITOR_SELL` path — **no LLM** on the hot path.
- On new data the PM may revise bounds, but they are only rewritten **when it trades
  again**; a plain HOLD keeps the existing bounds.

---

## 5. Every case, end to end

### 5a. Start of day — `CONTEXT_BUILD`
```mermaid
flowchart TD
  A["Tick 0, each ticker"] --> P{price available?}
  P -->|no| SKIPNP["skip (no price)"]
  P -->|yes| CRAG["CRAG: plan → retrieve → grade<br/>(retry ≤ 2 on bad retrieval)"]
  CRAG -->|INSUFFICIENT_EVIDENCE| REF["refuse honestly → remember"]
  CRAG -->|OK chunks| RESN["research → ResearchView"]
  RESN -->|NEUTRAL / INSUFFICIENT| NOACT["no actionable view"]
  RESN -->|BULLISH/BEARISH| SUB["PM → bounds → risk → execute<br/>(section 3)"]
```

### 5b. Middle — new data — `INCREMENTAL_NEWS`
New filing(s) since last tick. **Skips CRAG retrieval** — pushes the new chunks straight
to research with the prior view for context, then the section-3 sub-flow. Already-seen
docs are deduped via `processed_doc_ids` on the ticker memory.

### 5c. Middle — price moved — `PRICE_REEVAL`
Material move (≥ `price_move_threshold`, default 2%) with no new evidence.
**No retrieval, no re-research** — reuse the cached research view, re-run PM against the
new price (section 3). If the cached view is NEUTRAL/INSUFFICIENT, it no-trades.

### 5d. Middle — stop/target hit — `MONITOR_SELL`  (price up *or* down)
```mermaid
flowchart TD
  SCAN["stop_triggers: held positions,<br/>price vs avg_cost_basis × per-position bounds"]
  SCAN -->|"down through stop"| STOPL["STOP_LOSS"]
  SCAN -->|"up through target"| TAKEP["TAKE_PROFIT"]
  STOPL --> PS["protective sell:<br/>risk_engine (SELL auto-approves) → broker"]
  TAKEP --> PS
  PS --> BOOK["position reduced/closed, cash up"]
```
Fully deterministic. Both the downside (stop loss) and upside (take profit) exits go
through the same protective-sell path — no human gate, no LLM.

### 5e. Middle — hold / nothing
- PM returns **HOLD**, or sizing rounds to zero, or stance not actionable → `NoTrade`,
  recorded to memory, position (and its bounds) unchanged.
- No signal at all → dispatcher returns **SKIP**, the tick is a no-op.

### 5f. End of day — `DAY_REVIEW`
```mermaid
flowchart TD
  EOD["Last tick, each held position"] --> Q{position &amp; price?}
  Q -->|none| NOP["no position → record"]
  Q -->|yes| DELTA["delta-retrieve fresh evidence<br/>since last tick"]
  DELTA --> DRA["day_review agent:<br/>HOLD / TRIM / FLATTEN vs overnight gap risk"]
  DRA -->|HOLD| KEEP["keep position → record"]
  DRA -->|TRIM| TR["protective sell trim_fraction (50%)"]
  DRA -->|FLATTEN| FL["protective sell full position"]
```
`day_review` is the **overnight-gap** check and is distinct from intraday bounds: a
position can sit inside its stop/target band yet still be flattened pre-close for gap
risk. It is the only path that can do a **partial** (TRIM) exit.

---

## 6. Cross-cutting guardrails (apply on every path)

| Guardrail | Where | Effect |
|---|---|---|
| **CRAG corrective refusal** | `rag/crag.py` | Bad retrieval retries ≤ 2, then honest `INSUFFICIENT_EVIDENCE` — never fabricates a thesis. |
| **Injection quarantine** | `rag/retriever.py` → `guardrails/injection.py` | Scans retrieved chunks; prompt-injection content is quarantined out before it reaches an agent. |
| **Lookahead assertion** | `guardrails/lookahead.py` | Hard boundary: no document/price dated after `as_of` can enter context. |
| **Budget circuit-breaker** | `guardrails/budget.py` | Per-run caps on LLM calls / tokens / wall-clock; breach raises `BudgetExceeded` and **halts the whole run** (not isolated). Human-wait time is credited back. |
| **Exit-bound clamp** | `agents/pm.py` | LLM-proposed stop/target forced inside firm caps. |
| **Risk gate (HITL)** | `guardrails/risk_engine.py` + `firm/hitl.py` | BUYs ≥ notional threshold pause for the Risk Committee; SELLs auto-approve. |
| **Citations** | `guardrails/citations.py` | Research claims must carry evidence references. |
| **Partial-failure isolation** | `firm/runner.py` | One ticker's pipeline error degrades to an error span; the run continues. Budget/approval-timeout are the exceptions that halt. |
| **Deterministic execution** | `state/broker.py` | Slippage + commission, market-hours + no-oversell + idempotency, single-transaction fills. |

---

## 7. Outputs

- **Live event feed** — every span (`TICK`, `AGENT`, `LLM`, `GUARDRAIL`, `EXECUTION`,
  `HITL`) streams over SSE.
- **End-of-day report** (`/runs/:id/report[.xlsx]`) — deterministic metrics (equity,
  return vs benchmark, trades, process stats) narrated by the `reporting` agent, with a
  no-LLM deterministic fallback so the channel always works offline.
```
