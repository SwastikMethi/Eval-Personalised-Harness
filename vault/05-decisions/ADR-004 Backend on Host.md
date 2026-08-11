---
tags: [aso/adr]
status: accepted
date: 2026-07-30
updated: 2026-08-11
---

# ADR-004 — Backend runs natively on the host

Decided during eng review (Tension 3, 2026-07-30). Index: [[00 Index]].

## Context

Spec §5 and §26 both call for Docker Compose so `docker compose up` runs the whole app. But the backend **spawns sibling sandbox containers** via the host Docker daemon ([[Sandbox]]).

## Decision

`make dev` runs the backend as a **native host process** (uvicorn on port 8005). The control plane is not containerized for the MVP.

## Rationale

Containerizing the backend would require:

1. **Mounting `docker.sock`** into the backend container — a security-sensitive default, and awkward next to a spec that forbids that same mount for *sandbox* containers (§12, §23).
2. **Container→host path translation** for every workspace bind mount. The backend creates a workspace at some path and asks Docker to bind-mount it into the sandbox; the daemon resolves that path on the *host*, not inside the backend container.

Native-host dev avoids both footguns while the MVP is being built.

## Consequences

- One-command startup for new users does not exist yet — the distribution story is deferred. This is the standing item in `TODOS.md` and [[Roadmap]] Phase 11.
- `make dev` runs uvicorn **without `--workers`**, which is also what guarantees a single queue scheduler ([[Run Lifecycle]]).
- Evaluation commands run on the host too, at the same trust level as baseline validation. Documented as an MVP caveat in [[Evaluation Engine]]; moving evaluation into a fresh container is the next hardening step.

## Port note

Backend listens on **8005**, not the spec's 8000. `Makefile`, `config.py::backend_port`, `vite.config.ts`, and `queue.py::DOCKER_PROXY_BASE` all derive from one setting and must stay in agreement.

## Related

- [[Sandbox]] · [[System Overview]] · [[Make Targets]] · [[Evaluation Engine]]
