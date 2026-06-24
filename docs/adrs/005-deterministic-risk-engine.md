# ADR 005 — Hard trading limits in a deterministic risk engine (not the LLM)

**Status:** Accepted · **Date:** 2026-06-23

## Context
Brief requires "trading limits the system cannot exceed." An LLM can be prompt-injected or simply wrong; it must not be the thing that enforces money limits.

## Decision
A deterministic **Risk Engine** module is the **only** gate to the book. It evaluates every proposal and **re-checks immediately before fill** (state may change during HITL wait). Hard limits (configurable): max position % of equity, max single-order notional, max daily loss (kill-switch), max trades/day, no over-shorting, market-hours-only. Hard breach → `REJECT`, unbypassable by any agent (illegal trades never reach the human). **Every legal BUY → `REQUIRE_HUMAN`** — no silent auto-buy; risk-reducing sells may auto-approve. The Risk *agent* packages the case (thesis_card + citations) for the human; the *engine* enforces the hard limits.

## Alternatives
- **LLM-judged risk only** — flexible but bypassable/hallucinable; unacceptable for money.
- **Limits in prompts** — not enforceable; a single injection defeats them.

## Consequences
+ Limits provably cannot be exceeded; safety is code, not persuasion.
+ Pre-fill re-check closes the HITL-wait race.
− Less nuanced than an LLM; acceptable — LLM still provides narrative assessment.
