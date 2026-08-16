---
tags: [aso/adr]
status: accepted
date: 2026-08-11
updated: 2026-08-11
---

# ADR-002 — The three pinned models

Index: [[00 Index]].

## Context

Spec §2 wants "three selectable open-weight coding models", preferring free OpenRouter variants. The account has **no credits** (`GET /api/v1/key` → `is_free_tier: true`, usage 0), so paid models are out of reach regardless of merit.

A live query on 2026-08-11 found **only 14 free models** on OpenRouter — far fewer than the spec assumed. See [[Free Models]].

Kimi and GLM were requested and investigated: both exist on OpenRouter, both are open-weight, **neither has a `:free` variant**. Cheapest relevant option was `z-ai/glm-4.7-flash` at $0.06/$0.40 per M tokens — trivial money, but not zero, and there are no credits.

## Decision

| Model | Context | Why |
|---|---|---|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1M | Largest free model available; open-weight |
| `openai/gpt-oss-20b:free` | 131k | Apache-2.0, strong on code, fast — the small/fast contrast |
| `cohere/north-mini-code:free` | 256k | Purpose-built **code** model; best free coding bet |

Three vendors, 20B → 550B parameters, 131k → 1M context.

## Rationale

The spread is deliberate. Even at $0 cost, [[Scoring and Ranking]]'s **token efficiency**, **execution efficiency**, and **resource efficiency** dimensions need models that actually differ — three similar mid-size models would make those dimensions noise.

## Known deviation

`cohere/north-mini-code` is **not open-weight** (Cohere North is a proprietary product), so it bends §2's "open-weight" preference. It was chosen for coding strength on an explicit user instruction to pick the best *free* models.

**Swap to `google/gemma-4-31b-it:free`** if strict §2 compliance matters more than coding strength. Nemotron and gpt-oss are both genuinely open-weight.

## Consequences

- Every run costs $0; the constraint moves entirely to request quota — see [[ADR-003 Free Tier Constraints]].
- All three support tool calling, so none is blocked by harness requirements.
- Free variants come and go. §17's "never silently replace a selected model" means a vanished model must **fail its combination loudly**. `ModelSnapshot` pins exact IDs per experiment, so this is already handled — but expect to re-pick if a run is revisited weeks later.

## Related

- [[Free Models]] · [[Rate Limits]] · [[ADR-003 Free Tier Constraints]] · [[Milestones]]
