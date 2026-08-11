---
tags: [aso/reference]
status: current
updated: 2026-08-11
---

# Free Models

Live snapshot of OpenRouter's free tier, queried **2026-08-11**. Index: [[00 Index]].

> **402 total models on OpenRouter; only 14 are free.** This is far fewer than `generationDoc.md` assumed. Re-query before relying on this list — availability drifts.

```sh
curl -s https://openrouter.ai/api/v1/models \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
    [print(m['id'], m.get('context_length')) for m in d['data'] if m['id'].endswith(':free')]"
```

## The 14

| Model ID | Context | Tools | Open-weight |
|---|---|---|---|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1,000,000 | ✅ | ✅ |
| `inclusionai/ling-3.0-tiny:free` | 262,144 | ✅ | ✅ |
| `poolside/laguna-s-2.1:free` | 262,144 | ✅ | ✖ |
| `poolside/laguna-xs-2.1:free` | 262,144 | ✅ | ✖ |
| `google/gemma-4-26b-a4b-it:free` | 262,144 | ✅ | ✅ |
| `google/gemma-4-31b-it:free` | 262,144 | ✅ | ✅ |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262,144 | ✅ | ✅ |
| `cohere/north-mini-code:free` | 256,000 | ✅ | ✖ |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 256,000 | ✅ | ✅ |
| `nvidia/nemotron-3-nano-30b-a3b:free` | 256,000 | ✅ | ✅ |
| `openai/gpt-oss-20b:free` | 131,072 | ✅ | ✅ |
| `nvidia/nemotron-3.5-content-safety:free` | 128,000 | ✖ | ✅ |
| `nvidia/nemotron-nano-12b-v2-vl:free` | 128,000 | ✅ | ✅ |
| `nvidia/nemotron-nano-9b-v2:free` | 128,000 | ✅ | ✅ |

**Pinned for this project** (see [[ADR-002 Model Selection]]): `nvidia/nemotron-3-ultra-550b-a55b:free`, `openai/gpt-oss-20b:free`, `cohere/north-mini-code:free`.

**Unsuitable:** `nemotron-3.5-content-safety` is a safety classifier with no tool support; `nemotron-nano-12b-v2-vl` is vision-focused.

## Observed behaviour (2026-08-11, live runs)

| Model | Finding |
|---|---|
| `openai/gpt-oss-20b:free` | **Heavily throttled upstream** — 4 consecutive 429s before one success. Usable, but expect retries to eat the daily quota. |
| `cohere/north-mini-code:free` | Works well with **mini-SWE-agent** (14 steps, 14 shell commands). **Incompatible with smolagents**: returns tool-call JSON where smolagents expects `<code>` blocks → "Error in code parsing". |

The second row is the product working as intended: the same model is fine under one harness and unusable under another. Preflight ([[Roadmap]] Phase 5) should surface this before an experiment spends quota.

## Not free — investigated and ruled out

Kimi and GLM are both open-weight and both requested, but have **no `:free` variant**:

| Model | in $/M | out $/M |
|---|---|---|
| `z-ai/glm-4.7-flash` | 0.060 | 0.400 |
| `z-ai/glm-4.6` | 0.500 | 2.000 |
| `z-ai/glm-5.2` | 0.760 | 2.420 |
| `moonshotai/kimi-k2.7-code` | 0.700 | 3.500 |
| `moonshotai/kimi-k3` | 3.000 | 15.000 |

Cheap in absolute terms, but the account has no credits.

## Rules that bind model choice

- **Never** use `openrouter/free` — it routes to arbitrary underlying models and destroys controlled comparison. The provider bans it explicitly.
- Identify free variants by pricing metadata **and** the `:free` suffix.
- Save the exact model ID and metadata with every experiment (`ModelSnapshot`).
- **Never silently replace a selected model.** If one becomes unavailable, fail that combination clearly.

## Related

- [[Rate Limits]] · [[ADR-002 Model Selection]] · [[Model Proxy]]
