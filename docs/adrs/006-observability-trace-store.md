# ADR 006 — Self-contained durable trace store (replay-from-trace)

**Status:** Accepted · **Date:** 2026-06-23

## Context
Brief: "a reviewer should be able to replay a trade end-to-end from the trace alone." Needs durable, queryable, committable traces — not just ephemeral logs or an external SaaS the reviewer can't access.

## Decision
OpenTelemetry-style **spans persisted to a `Span` table** (durable, queryable) and mirrored to **JSONL artifacts committed with the sample run**. Every agent node, tool call, LLM call, guardrail check, and DB write is a span carrying input/output JSON, model, tokens, cost, latency, status — correlated by `run_id` + `trade_id` into a causal tree. `GET /trades/{id}/trace` returns the tree; a React Trace Viewer renders it. `structlog` JSON logs share the same correlation ids. OTLP export seam left for prod.

## Alternatives
- **LangSmith / hosted tracing only** — great DX but external, key-gated, not committable; reviewer can't replay offline.
- **Plain logs** — not a queryable causal tree; fails "replay from trace alone."

## Consequences
+ Offline, committed, replayable audit trail; strongest live-demo artifact.
+ Token/cost accounting falls out of the same spans.
− We maintain a small trace schema; acceptable and keeps zero external deps.
