---
tags: [aso/moc]
status: current
updated: 2026-08-11
---

# Agent Stack Optimizer — Index

Entry point for this vault. Everything links from here.

> **What this is.** A local, single-user platform that benchmarks combinations of *coding-agent harness × open-weight model × config* against real tasks from your own Git repository, then recommends the best quality / reliability / efficiency / balanced stack.
>
> **The central question:** for this repository and these coding tasks, which harness-model combination gives the best quality, reliability, and efficiency at the lowest practical cost?

This is **not a model leaderboard**. It evaluates the complete agent stack.

## Start here

| If you want to… | Read |
|---|---|
| Understand the product | [[Product Goal]] · [[Spec Scope]] |
| Know what actually works today | [[Implemented]] · [[Known Defects]] |
| Understand the system | [[System Overview]] · [[End-to-End Flow]] · [[Run Lifecycle]] |
| Understand the safety model | [[Leakage Prevention]] · [[Model Proxy]] · [[Sandbox]] |
| Know what to build next | [[Roadmap]] · [[Milestones]] · [[UI Rebuild]] |
| Know why something is the way it is | [[ADR-001 Harness Choice]] · [[ADR-002 Model Selection]] · [[ADR-003 Free Tier Constraints]] · [[ADR-004 Backend on Host]] |
| Find a file in the codebase | [[Codebase Map]] |
| Run something | [[Make Targets]] |

## Product

- [[Product Goal]] — what it answers and for whom
- [[Spec Scope]] — what is in and explicitly out
- [[Acceptance Criteria]] — the 25 items that define "done", with live status

## Architecture

- [[System Overview]] — components and how they connect
- [[End-to-End Flow]] — every stage from repo to recommendation, and the tech behind each
- [[Run Lifecycle]] — the 9-state machine, crash recovery
- [[Leakage Prevention]] — **the core invariant**; historical replay is worthless without it
- [[Model Proxy]] — run tokens, model pinning, budgets
- [[Sandbox]] — Docker isolation, two-phase network
- [[Evaluation Engine]] — how a patch is graded
- [[Scoring and Ranking]] — weights, eligibility, Pareto

## Status

- [[Implemented]] — verified working, not just claimed
- [[Known Defects]] — the 7 blocking defects
- [[Spec Gaps]] — what the spec asks for that does not exist yet

## Plan

- [[Roadmap]] — Phases 0–11
- [[Milestones]] — Milestone A (6-run smoke) and B (scaled matrix)
- [[UI Rebuild]] — 3D shell, agent-led setup, live agent telemetry, KPI comparison

## Decisions

- [[ADR-001 Harness Choice]] — smolagents before OpenHands, and why
- [[ADR-002 Model Selection]] — the three free models
- [[ADR-003 Free Tier Constraints]] — why quota, not money, sets the schedule
- [[ADR-004 Backend on Host]] — why the control plane is not containerized
- [[ADR-005 Second Provider]] — NVIDIA NIM, and what "unknown" must not become

## Reference

- [[Free Models]] — the 14 free OpenRouter models with context and tool support
- [[Rate Limits]] — free-tier caps and what they imply
- [[Make Targets]] — every command and whether it works
- [[Codebase Map]] — file → responsibility

## Log

- [[Session Log]] — what changed, when, and why

---

## The one thing to never break

The agent container **never holds the OpenRouter key, never sees the solution commit, and has no route to the internet except the model proxy.** Every change is measured against this. See [[Leakage Prevention]].
