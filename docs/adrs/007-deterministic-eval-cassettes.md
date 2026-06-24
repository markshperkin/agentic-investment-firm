# ADR 007 — Deterministic eval via frozen data + recorded LLM cassettes

**Status:** Accepted · **Date:** 2026-06-23

## Context
Eval harness must be a reproducible historical replay, run in CI, report return AND process metrics honestly — without burning tokens or needing API keys in CI.

## Decision
Determinism from three frozen inputs: **market snapshot** (parquet, committed), **time-boxed corpus** (committed), and **recorded LLM responses** (one cassette per call, keyed by prompt hash). CI replays cassettes → no key, no cost, deterministic. Metrics: return (P&L, vs-SPY alpha, drawdown, turnover) + process (groundedness, citation validity, refusal correctness, guardrail effectiveness on seeded adversarial cases, schema-valid rate, cost/run). Thresholds gate the CI job. Output → `docs/eval-report.md` + committed JSON.

## Alternatives
- **Live LLM in CI** — non-deterministic, costs tokens, needs secrets; flaky.
- **Return metrics only** — misses the process-quality rigor graders reward.

## Consequences
+ Reproducible, free, key-less CI; honest dual-axis metrics.
+ Seeded adversarial cases prove guardrail/refusal effectiveness.
− Cassettes can drift from live model behavior; mitigated by a separate non-CI live smoke run.
