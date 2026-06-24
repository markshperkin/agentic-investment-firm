# ADR 001 — LangGraph for orchestration + HITL

**Status:** Accepted · **Date:** 2026-06-23

## Context
Need a 5-agent workflow with persistent state between agents, a human-in-the-loop pause where "graph state persists across the wait," and crash recovery. The brief's HITL wording maps almost literally to a checkpointed graph.

## Decision
Use **LangGraph**. Agents = nodes; `FirmState` flows through edges; `SqliteSaver` checkpointer persists state at every node; `interrupt()` pauses before the Risk Committee and resumes from the persisted checkpoint on the approval API call.

## Alternatives
- **Custom state machine** — full control but we'd rebuild checkpoint + interrupt/resume + replay; too much risk in a 3–4 day build.
- **CrewAI / AutoGen** — higher-level role abstractions but weaker first-class durable interrupt/resume + checkpointing.

## Consequences
+ Durable HITL pause/resume and crash recovery out of the box; idempotency keys prevent double-execution on resume.
+ Clear node/edge model = legible architecture diagram + traces.
− Framework coupling; mitigated by keeping agent logic in plain typed functions the nodes call.
