---
tags: [aso/log]
status: current
updated: 2026-08-11
---

# Session Log

Append-only. Newest first. One entry per meaningful chunk of work. Index: [[00 Index]].

Keep entries short: **what changed · why · what it unblocks · what to verify.**

---

## 2026-08-11 — Phase 0: knowledge base

**What.** Created this vault (`vault/`) and root `CLAUDE.md`. Branch `worktree-aso-full-build`.

**Why.** Every session was re-deriving the same context from a 1,406-line spec plus 4,100 lines of source. The vault makes the verified findings durable and the [[Roadmap]] explicit.

**Findings recorded.** Seven blocking defects ([[Known Defects]]) found by reading code — most importantly that `create_snapshot()` is never called by the queue, so **historical replay does not actually work** and the system has never run a real benchmark.

**Decisions locked.** [[ADR-001 Harness Choice]] (smolagents before OpenHands), [[ADR-002 Model Selection]] (three free models), [[ADR-003 Free Tier Constraints]] (quota sets the schedule), [[ADR-004 Backend on Host]] (recorded from the earlier eng review).

**Baseline at start.** 77 backend tests passing; 15 of 25 acceptance criteria fully met ([[Acceptance Criteria]]).

**Next.** Phase 1 — Alembic scaffolding, `app/seed.py`, frontend test infra. See [[Roadmap]].

---

<!-- New entries above this line -->
