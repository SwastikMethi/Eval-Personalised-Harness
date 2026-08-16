---
tags: [aso/adr]
status: accepted
date: 2026-08-11
updated: 2026-08-11
---

# ADR-001 — smolagents before OpenHands

Index: [[00 Index]].

## Context

`generationDoc.md` §3 names three harnesses: **OpenHands Software Agent SDK**, **mini-SWE-agent**, **smolagents CodeAgent**. Only mini-SWE-agent exists. With one harness the matrix cannot answer the [[Product Goal]] question — it compares one harness against itself.

The binding architectural constraint comes from [[Sandbox]]: **the harness runs *inside* the sealed container**, so its shell commands are jailed and its only network path is the [[Model Proxy]]. `mini_swe_agent.py` does this via `manager.exec(...)`, and the harness is installed in the sandbox image.

## Decision

Build **smolagents second**, **OpenHands last** (Phase 10).

## Rationale

| | smolagents | OpenHands |
|---|---|---|
| Install | `pip install smolagents` — pure Python | Large dep tree, heavy image |
| Execution model | Runs code in-process | Normally spawns its **own Docker runtime container** |
| Fits sealed sandbox? | Yes, unchanged security model | **No** — needs docker-in-docker or a socket mount |
| Needs tool calling? | No — parses code from message content | **Yes** |
| Risk | Low | High |

Two hard blockers for OpenHands:

1. **Docker socket.** Spec §12 and §23 both forbid mounting `docker.sock` into the sandbox. OpenHands' default runtime needs one. Its local/CLI runtime is the only compliant path.
2. **Tool calls.** The proxy currently destroys them ([[Known Defects]] #5). smolagents is immune because it reads code out of `message.content`; OpenHands is not.

## Consequences

- A real 2-harness comparison is reachable in Phase 4 rather than blocked behind OpenHands' runtime problem.
- Phase 3 must fix tool-call passthrough anyway — it is a prerequisite for Phase 10.
- If OpenHands' local runtime proves unworkable, the fallback is a subprocess adapter over its supported CLI, preserving the same normalized telemetry contract. §3 explicitly permits this.
- **Do not hide the constraint.** If OpenHands cannot be sandboxed compliantly, document that rather than quietly mounting a socket.

## Related

- [[Sandbox]] · [[Model Proxy]] · [[Roadmap]] · [[Spec Gaps]]
