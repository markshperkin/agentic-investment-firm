# Agentic Investment Firm

A multi-agent system that operates an AI-run paper-trading investment firm over a replayed US trading day. Six reasoning agents (Query-Gen, Relevance-Critic, Research, PM, Risk, Reporting) collaborate over a deterministic LangGraph orchestrator, ground every decision in a time-boxed RAG corpus with citations, route every buy through a human Risk Committee, and leave a full, replayable trace of every action.

> Design priority: **agentic system → guardrails → observability.** Reliability and safety over features.

## Monorepo layout

```
server/   FastAPI backend + the agent system (LangGraph, RAG, risk engine, paper broker, trace store)
web/      React dashboard (event feed, approvals inbox, portfolio, belief-evolution)
docs/     PRD, architecture, ADRs — the design of the system
```

## Documentation

- [`docs/prd.md`](docs/prd.md) — product requirements
- [`docs/architecture.md`](docs/architecture.md) — system architecture (agents, pipeline, trigger clock, guardrails, observability, data model, APIs)
- [`docs/adrs/`](docs/adrs/) — architecture decision records

## Status

Design phase. Build plan and runnable system to follow.
