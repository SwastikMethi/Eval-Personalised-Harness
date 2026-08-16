---
tags: [aso/status]
status: current
updated: 2026-08-11
---

# Spec Gaps

Things `generationDoc.md` asks for that do not exist yet. Distinct from [[Known Defects]], which are things that exist but are wired wrong. Index: [[00 Index]].

## Harnesses (§3)

Only **mini-SWE-agent** (+ a fake). Missing: **smolagents CodeAgent**, **OpenHands**. With one real harness the matrix cannot answer the [[Product Goal]] question. → Phases 4, 10. See [[ADR-001 Harness Choice]].

## Preflight / compatibility (§21)

Entirely absent — grep finds nothing. Spec wants per harness-model checks (endpoint, tool-calling, structured output, context length, known-bad combinations) plus a live preflight that edits one file in a tiny fixture and verifies the patch. → Phase 5.

## Live streaming (§5, §19)

No SSE, no WebSocket anywhere. The UI polls. → Phase 8.

## Evaluator architecture (§15)

One `evaluate()` function instead of the composable `Evaluator` ABC with ten named evaluators. `Lint` and `TypeCheck` evaluators do not exist. → Phase 6. See [[Evaluation Engine]].

## Data model (§18)

14 of 19 tables. Missing:

- `HistoricalTaskMetadata`
- `ModelProviderConfiguration`
- `HarnessDefinition`
- `HarnessMetric`
- `SandboxMetric`
- `Recommendation`

So harness/sandbox metrics are collected (`manager.stats()`) but never persisted, and recommendations are recomputed on every read. → Phase 7.

## Migrations (§5, §18)

Alembic is a declared dependency with no scaffolding. → Phase 1.

## Frontend (§20)

2 of 7 screens (`Dashboard`, `ExperimentDetail`). Missing: onboarding wizard, task selection, experiment configuration with matrix preview, results screen, run detail. Recharts and React Router are installed but barely used. → Phase 9.

## API (§19)

Missing: preview run matrix · cancel experiment · stream experiment events · get recommendations · run logs/patch/events/evaluator-results/resource-metrics · PR metadata fetch. → Phase 8.

## Testing (§24)

Zero frontend tests, no vitest, no Playwright smoke test. → Phases 1, 9.

## Task sources (§8.2)

PR replay not implemented (commit replay is). → Phase 11.

## Packaging and ops (§25, §26, §28)

- No `docker-compose.yml` — see [[ADR-004 Backend on Host]]
- No diagnostics page
- No TypeScript fixture, no `sandbox-images/node/`

→ Phase 11.

## Related

- [[Known Defects]] · [[Roadmap]] · [[Acceptance Criteria]]
