# ADR 004 — Anthropic LLMs with cost-aware routing

**Status:** Accepted · **Date:** 2026-06-23

## Context
Brief flags token consumption + cost as evaluation concerns and offers cost-aware routing as bonus. Need cheap high-volume calls but stronger reasoning for trade decisions. Must run in CI without spend.

## Decision
Single `LLMRouter` over **Anthropic**. **`claude-haiku-4-5`** default (Research grounding, Reporting); **escalate to `claude-sonnet-4-6`** for PM trade decisions + Risk explanations. Per-call cost/tokens recorded in spans. Provider interface allows a **recorded-cassette / local provider** for offline deterministic CI.

## Alternatives
- **Single large model everywhere** — simpler, higher cost/tokens; ignores the evaluation note.
- **OpenAI** — fine, but Anthropic is the stated/assumed provider and structured-output + tool-use fit the typed-contract design.

## Consequences
+ Lower token spend; cost-routing bonus earned cheaply; cost visible per run in traces.
− Two-model complexity; mitigated by one routing abstraction with a simple task→tier map.
