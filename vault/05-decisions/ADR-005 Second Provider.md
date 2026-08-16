---
tags: [aso/adr]
status: accepted
date: 2026-08-12
updated: 2026-08-12
---

# ADR-005 — NVIDIA NIM as a second provider

Index: [[00 Index]].

## Context

OpenRouter's free tier (~50 requests/day, no credits) has been the binding constraint on the entire project — see [[ADR-003 Free Tier Constraints]]. It is why [[Milestones]] Milestone A was sized at 6 runs and why the full matrix was estimated at six days. Nothing else on the roadmap was gated as hard.

Spec §4 already lists "any OpenAI-compatible endpoint" as a planned provider, and `providers/base.py::ModelProvider` is the seam.

## Decision

Add `NimProvider` as a **second** provider, selected per combination. OpenRouter stays.

Verified against the live API: `GET /v1/models` returns **102 models** (49 code-oriented — DeepSeek Coder, StarCoder2, CodeGemma, Granite, Llama, Nemotron) and needs no key to list.

## The honesty consequence

NIM's listing carries only `id`, `object`, `created`, `owned_by`. No pricing, no context length, no `supported_parameters`. So:

- `supports_tools` and `supports_structured_output` became **`bool | None`** across the shared contract. `None` means *unknown*, not unsupported. Reporting `False` would be inventing a capability report, which spec §31 forbids.
- The UI renders `tools unknown`, never `no tools`.
- `is_free` is **False** for every NIM model. It bills credits, so presenting one as free-tier would be a lie of a different kind; a NIM run must not show "$0.00" the way a genuine OpenRouter `:free` model does.

`is_moving_alias()` moved from `openrouter.py` to `base.py` — an alias is unpinnable for any provider, and leaving the rule inside one invites the next to forget it.

## Consequences

- Comparing the **same open-weight model across two providers** becomes a legitimate experiment in its own right.
- The quota constraint changes shape, not existence: NIM credits are finite too, so `max_model_requests` and the `RATE_LIMITED` backoff are unchanged.
- `tools unknown` is unsatisfying and is the strongest argument yet for building spec §21 **preflight**, which would settle capability empirically rather than by listing metadata.
- **Unverified:** NIM's rate limits and credit allowance. That needs a key; nothing in the implementation assumes anything about them, and the existing 429 handling covers whatever they are.

## Related

- [[ADR-003 Free Tier Constraints]] · [[ADR-002 Model Selection]] · [[Model Proxy]] · [[Free Models]]
