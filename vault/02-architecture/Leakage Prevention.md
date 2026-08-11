---
tags: [aso/architecture, aso/invariant, aso/security]
status: current
updated: 2026-08-11
---

# Leakage Prevention

**The core invariant.** Historical replay is worthless if the agent can reach the answer. Source: `generationDoc.md` §9. Index: [[00 Index]].

## What the sandbox must never contain

- The target solution commit
- The final historical patch
- Hidden tests (before the agent stops)
- Future repository history
- Remote Git config that enables fetching the answer
- GitHub PR diff URLs
- Unrestricted internet access

## The four defences

### 1. Clean snapshot

`git archive` at the **base** commit → extracted into a fresh directory → `git init` → one synthetic commit. No original history, no remotes, no hooks. The solution commit never enters the sandbox.

Implemented: `app/repositories/service.py::create_snapshot`, called from `app/orchestration/queue.py::materialize_workspace` for every run whose task has a base commit. Grading rebuilds its own fresh snapshot rather than reusing the agent's workspace.

Fixture-driven demos fall back to a plain directory copy — they have no history to leak. A task with neither a base commit nor a fixture raises instead of silently grading the wrong tree.

### 2. Two-phase network

- **PREP** — container on the default bridge; dependency install and baseline run *before any agent code executes*
- **AGENT** — bridge disconnected, container joined to a per-run `internal: true` network. Internal networks have no default route, so general egress is dead. The proxy stays reachable via `host.docker.internal` (host-gateway mapping).

`seal()` **fails closed**: it probes external egress and refuses to report sealed if the probe succeeds.

Implemented: `app/sandboxes/manager.py::seal`. See [[Sandbox]].

### 3. Conservative hidden tests

Extracted from the target commit, but:
- Tests importing target-only modules are **rejected** (they cannot pass against any agent result missing that module)
- Confidence and provenance recorded
- User approves or rejects before the experiment runs
- They run **only after** the agent stops, with no further editing

Implemented: `app/tasks/historical.py::extract_hidden_tests`.

### 4. No key in the container

The container receives a short-lived per-run token, never the OpenRouter key. See [[Model Proxy]].

## Evaluation happens outside the workspace

Grading never runs in the agent's workspace. The only agent input to grading is **the patch**, applied to a fresh snapshot with evaluator-owned commands. See [[Evaluation Engine]].

## How to verify

```sh
# in the sandbox workspace
git log --oneline        # exactly one synthetic commit
git remote -v            # empty
ls .git/hooks            # empty
# egress probe must report BLOCKED after seal()
```

Plus: dump container env and assert the OpenRouter key is absent.

## Related

- [[Sandbox]] · [[Model Proxy]] · [[Evaluation Engine]] · [[Known Defects]]
