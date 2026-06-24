# ADR 002 — SQLite + SQLAlchemy for portfolio state

**Status:** Accepted · **Date:** 2026-06-23

## Context
Portfolio state (cash, holdings, cost basis, P&L) must be transactional, survive a restart, and reconcile cleanly after a mid-cycle crash. Single-process demo; reviewer must run it in <10 min with no infra.

## Decision
**SQLite** via **SQLAlchemy ORM**. Every book mutation (fill) is one ACID transaction writing Trade + Position + PnLSnapshot atomically. Invariant `cash + Σ holdings = equity` recomputed on startup. Trade `idempotency_key` makes resume safe.

## Alternatives
- **Postgres** — needed for concurrent-write scale we don't have; adds a service to the demo path.
- **JSON file / pickle** — no ACID, corrupts on crash mid-write. Disqualifying for money state.

## Consequences
+ Zero-ops, file-based, commits to repo; ACID gives crash recovery for free.
+ ORM makes Postgres a config swap → documented production path.
− Single-writer; fine for one firm process.
