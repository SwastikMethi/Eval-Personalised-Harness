---
tags: [aso/product, aso/scope]
status: current
updated: 2026-08-11
---

# Spec Scope

Source: `generationDoc.md` §2. Index: [[00 Index]].

## In scope (MVP)

- Coding-related repository tasks
- One repository per experiment
- Local Git repositories and public GitHub repository URLs
- Three open-source coding harnesses
- Three selectable open-weight coding models
- OpenRouter as the first hosted inference provider
- Free OpenRouter model variants where available — see [[Free Models]]
- Local Docker sandboxing — see [[Sandbox]]
- Existing-test evaluation
- Historical commit replay
- Historical PR replay when GitHub metadata is available
- Sequential or limited-concurrency execution
- Metrics collection
- Side-by-side comparison
- Recommendation generation
- Local single-user dashboard

## Explicitly out of scope

Create extension points, but **do not implement**:

- Authentication · Multi-tenancy · Billing · Teams/organizations
- Cloud sandbox infrastructure · Kubernetes
- Research or browser benchmarks
- A public benchmark marketplace
- Fine-tuning · Training models
- **Support for closed-source paid models**
- Complex distributed infrastructure

Also banned by §5: Redis, Celery, Kafka, Kubernetes, PostgreSQL.

## The "open-weight" rule, interpreted

§2 bans *closed-source* models, not *paid* ones. An open-weight model behind a paid endpoint (Kimi K2, GLM) is compatible in principle; a closed model (GPT-4, Claude) is not, free or otherwise.

In practice this project runs on free variants because the account has no credits — see [[ADR-002 Model Selection]] and [[ADR-003 Free Tier Constraints]].

## Extension points that must exist

- **Providers** — `app/providers/base.py::ModelProvider`; Ollama/vLLM/llama.cpp/Groq/HF fit behind the same shape
- **Harnesses** — `app/harnesses/base.py::HarnessAdapter` + `register()`
- **Evaluators** — `app/evaluators/engine.py`

See [[Codebase Map]].

## Related

- [[Product Goal]] · [[Acceptance Criteria]] · [[Spec Gaps]]
