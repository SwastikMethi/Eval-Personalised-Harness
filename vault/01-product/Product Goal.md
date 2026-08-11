---
tags: [aso/product]
status: current
updated: 2026-08-11
---

# Product Goal

Source: `generationDoc.md` §1. Index: [[00 Index]].

## The question

> For this repository and these coding tasks, which harness-model combination gives the best quality, reliability, and efficiency at the lowest practical cost?

## What it evaluates

Combinations of three things, together — not any one in isolation:

1. **Coding-agent harness** (mini-SWE-agent, smolagents, OpenHands)
2. **Open-weight coding model** served through an API (OpenRouter)
3. **Agent configuration** (steps, temperature, timeouts, resource limits)

…against **real tasks from a user-selected Git repository**, not a public benchmark.

## Dimensions measured

- Correctness
- Reliability
- Execution efficiency
- Token efficiency
- Estimated cost
- Developer productivity

## Why "not a leaderboard" matters

A model that scores well in isolation may perform badly inside a particular harness — the harness controls prompting, tool surface, parsing, retry behaviour, and step budget. The same model can be excellent under one harness and useless under another. Measuring the **stack** is the product; measuring models alone is a commodity.

This is why [[ADR-001 Harness Choice]] treats "get a second harness working" as higher priority than "add more models" — with one harness the matrix cannot answer the central question at all.

## Positioning

First version is **local-only and single-user**. See [[Spec Scope]] for what that excludes, and [[ADR-004 Backend on Host]] for the packaging consequence.

## Related

- [[Spec Scope]] — boundaries
- [[Acceptance Criteria]] — how we know it is done
- [[Scoring and Ranking]] — how the dimensions become a recommendation
