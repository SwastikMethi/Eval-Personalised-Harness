# TODOS

## Compose packaging for the backend (Docker socket mount + host path translation)
- **What:** Make `docker compose up` run the full app (backend containerized), documenting the docker.sock mount tradeoff and workspace path mapping between container and host.
- **Why:** Distribution story for users who aren't the developer; today `make dev` runs the backend natively on the host (decided in eng review Tension 3, 2026-07-30).
- **Pros:** One-command startup for new users; consistent packaging.
- **Cons:** Socket mount is a security-sensitive default; every workspace bind mount needs container→host path translation.
- **Context:** The backend spawns sibling sandbox containers via the host Docker daemon, which is why containerizing the control plane is non-trivial. Native-host dev avoids both footguns during the MVP build.
- **Depends on / blocked by:** Stages 1–4 of the implementation plan existing and stable.
