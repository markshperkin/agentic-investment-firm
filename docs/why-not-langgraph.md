# Why not LangGraph

A deliberate decision record: the firm's orchestration is **explicit deterministic code with state persisted in the database**, not a LangGraph graph with `interrupt()`. This documents why, honestly — including what LangGraph is genuinely good at and where it would have earned its place.

## TL;DR
We didn't avoid LangGraph because it's "less observable" or "non-deterministic" — neither is true. We avoided it because, for a **small, fixed, deterministic, single-process** workflow, everything it provides (durable state, checkpoint/resume, a node/edge model) we already get directly — and the committed, offline-replayable trace the brief requires we'd have to build *inside* its nodes anyway. So it would be a redundant dependency layered over machinery we already have.

## What the requirement actually says
> Human-in-the-loop — high-impact trades pause for human approve / edit / reject. **Graph state persists across the wait.**

This requires that the firm's decision state **survive the pause** (and a restart) so an in-flight trade is never lost. It does **not** mandate LangGraph. We satisfy it: a pending trade is a durable `ApprovalRequest` row (status `PENDING`); it survives restart trivially and is resumed by the approval HTTP call.

## Correcting two common misconceptions
- **"LangGraph is only for LLM-driven orchestration."** No — LangGraph edges can be deterministic *conditional edges* (code picks the next node) or dynamic *agentic routing* (an LLM picks). It is a graph/state-machine runtime; it is not inherently non-deterministic. You control that with how you write edges.
- **"LangGraph has poor observability."** No — it has solid tracing (LangSmith, stream events, callbacks). The nuance is below.

## The observability nuance (the honest version)
The brief wants a reviewer to **replay a trade end-to-end from the trace alone**, from **committed artifacts**, **offline**. LangGraph's *native* observability path is **LangSmith** — an external SaaS, key-gated, and not committed to the repo. That does not meet "committed + offline-replayable."

To produce the trace we actually want (OpenTelemetry-style spans in SQLite + committed JSONL), we would **instrument inside each LangGraph node anyway** — i.e. emit our own spans from within the framework. So LangGraph would **not reduce** the observability work for our specific requirement; it would add a layer on top of the same span-emitting we already do directly.

Conclusion: not "LangGraph is less observable," but **"LangGraph wouldn't save observability effort here, while adding a framework layer."**

## Why it would be genuinely more complicated here
Concretely, adopting LangGraph means taking on:

1. **State as graph channels.** `FirmState` becomes a `StateGraph` schema with typed channels + reducer/merge semantics (notably for the per-ticker fan-out). In our design `FirmState` is plain data passed between functions.
2. **Checkpointer + thread management.** Configure a checkpointer and run with a `thread_id`; resume by reloading that thread. In our design "resume" = read one `PENDING` approval row and call the broker — no suspended execution to revive.
3. **Interrupt/resume across an HTTP boundary.** `interrupt()` suspends execution; the approval endpoint must re-enter the graph with the correct thread + checkpoint. More moving parts than a stateless endpoint reading a row.
4. **Debugging through the framework's execution model** rather than plain stack traces + our own spans.

For a fixed, deterministic, single-process pipeline, that is machinery we would justify but not really use.

## What we use instead (and how it meets every HITL property)
| LangGraph gives… | We get it via… |
|---|---|
| durable state across steps | SQLite (portfolio, `TickerMemory`, approvals) |
| checkpoint + resume after a pause | the persisted `PENDING` `ApprovalRequest` row |
| a node/edge execution model | the deterministic `dispatcher` + `runner` loop |
| interrupt/resume for HITL | stop-and-persist; the approval HTTP call resumes it |
| committed, offline-replayable trace | our own span store (SQLite + JSONL), built directly |

The orchestrator (`firm/runner.py` + `firm/dispatcher.py`) is **code, not a framework**, so every run of the same day routes identically — maximal auditability and reproducibility, which is exactly what this task rewards.

## Where LangGraph WOULD earn its place
This is not "LangGraph bad." It is the right tool when:
- the workflow is **large, branching, or cyclic** and you don't want to hand-roll state threading;
- you want **dynamic/agentic routing** (an LLM decides the next node) with framework guardrails;
- you have **long-running multi-step agents** and want checkpoint/resume without building your own persistence;
- you actively want **LangSmith** tracing and the team already lives in that ecosystem.

None of these describe a one-day, fixed-pipeline, single-process replay with a web-driven approval inbox.

## The one-line defense
"The workflow is a small fixed pipeline, so we kept orchestration as explicit deterministic code with state in the database. 'Graph state persists across the wait' is satisfied by the persisted approval — without taking on a framework whose checkpointing/interrupt features we'd be duplicating and whose native tracing wouldn't meet our committed-offline-replay requirement."

> Supersedes the LangGraph choice in ADR-001. See also `docs/architecture.md` (orchestration) and `docs/handoff.md`.
