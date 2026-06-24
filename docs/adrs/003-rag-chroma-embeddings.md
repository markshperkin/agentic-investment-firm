# ADR 003 — RAG: Chroma + provider-abstracted embeddings, time-boxed + citation-disciplined

**Status:** Accepted · **Date:** 2026-06-23

## Context
Decisions must be grounded in citable evidence — no hallucinated numbers/dates/quotes — and the corpus must never expose documents dated after the replay day (no lookahead). Must run offline in CI.

## Decision
- **Corpus source:** **SEC EDGAR only** (10-K/10-Q for citable numbers; 8-K + press-release exhibits for events/triggers). Public-domain (safe to commit to the public repo), authoritatively timestamped (acceptance datetime = `published_date`), date/form/company queryable, deep history (any past trading day usable). No third-party news APIs.
- **Vector store:** **Chroma** (persistent, local, no service); vectors keyed by `Chunk.id`, metadata `{ticker, published_date, source, form_type}`.
- **Embeddings:** **Voyage `voyage-3.5`** (chosen for retrieval quality), provider-abstracted with a **local `bge-small` fallback** so CI runs offline/$0. Vectors persisted once → CI replays stored vectors, never re-embeds, so the Voyage key isn't needed at replay/CI time.
- **Time-boxing:** retrieval filters `published_date <= as_of_date` at query time.
- **Citation discipline:** post-retrieval verifier requires every numeric/stance claim to map to a retrieved `chunk_id`; quotes substring-checked; else forced to `INSUFFICIENT_EVIDENCE`.

## Alternatives
- **FAISS** — fast but no built-in metadata filtering/persistence ergonomics needed for time-boxing.
- **Pinecone/Weaviate (hosted)** — external dependency in the demo path; rejected.

## Consequences
+ Deterministic, offline, lookahead-safe retrieval with enforced citations.
− Local embeddings lower retrieval quality than Voyage; mitigated by small curated corpus + Voyage option.
