---
tags: [aso/architecture, aso/security]
status: current
updated: 2026-08-11
---

# Model Proxy

Source: `generationDoc.md` §12. Implemented in `app/api/proxy.py`. Index: [[00 Index]].

## Why it exists

Agent containers must never receive the real OpenRouter API key. The proxy is the only thing that holds it.

```
Sandbox harness
    |  OpenAI-compatible request + short-lived run token
    v
Local model proxy (backend)
    |  real OpenRouter API key
    v
OpenRouter
```

## What it enforces

| Guard | Mechanism |
|---|---|
| Valid run | Constant-time token comparison against `_active_tokens` |
| Token expiry | `TOKEN_TTL_S` = 2h, renewable via `renew_run_token()` |
| **Model pinning** | Request model must equal the run's pinned model, else 403 |
| Request budget | `max_requests` per run |
| Token budgets | `max_input_tokens` / `max_output_tokens` |
| Spend ceiling | `max_cost_usd` |
| Telemetry | One `ModelRequestMetric` row per request |
| Secrecy | Key never logged, echoed, or returned |

`openrouter/free` is **banned outright** — it routes to arbitrary underlying models, which destroys controlled comparison.

## Token lifecycle

`issue_run_token()` at `PREPARING` → used throughout `RUNNING` → `revoke_run_token()` in the `finally` block, so a token cannot outlive its run.

## Two defects to know about

1. **Cost accounting is inert.** `queue.py` calls `issue_run_token()` without `input_price`/`output_price`, so `cost_usd` never leaves 0.0 and the ceiling cannot fire. Free models make this $0 anyway, but §14 requires cost recorded even when zero.
2. **Tool calls are destroyed.** `chat_completions` returns a hand-built response with only `message.content` and a hardcoded `finish_reason: "stop"`; `ChatRequest` has no `tools` field. smolagents survives (it parses code from content); **OpenHands cannot work** until this is fixed.

Both in [[Known Defects]] (#4, #5); fixed in [[Roadmap]] Phase 3.

## Rule from §12 worth repeating

> Do not log hidden reasoning. Store only observable messages, actions, tool calls, responses, usage data, and errors that the harness exposes for legitimate telemetry.

## Related

- [[Leakage Prevention]] · [[Sandbox]] · [[Rate Limits]] · [[Known Defects]]
