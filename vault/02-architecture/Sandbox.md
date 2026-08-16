---
tags: [aso/architecture, aso/security]
status: current
updated: 2026-08-11
---

# Sandbox

Source: `generationDoc.md` §12. Implemented in `app/sandboxes/manager.py`. Index: [[00 Index]].

## Per-run guarantees

Fresh container · fresh repository snapshot · non-root user (uid 1000) · dedicated writable workspace · CPU/memory/PID limits · wall-clock timeout · no privileged mode · **no host Docker socket** · no host mounts except the prepared workspace · restricted network · automatic cleanup · captured stdout/stderr and exit state.

Hardening applied at create: `security_opt=["no-new-privileges"]`, `cap_drop=["ALL"]`, `tmpfs=/tmp`.

## Default limits

```yaml
cpu_limit: 2
memory_limit_mb: 4096
pids_limit: 256
timeout_seconds: 1800
network_mode: restricted
max_output_bytes: 10000000
```

Configurable per experiment.

## Two-phase network

| Phase | Network | Purpose |
|---|---|---|
| **PREP** | default bridge, egress allowed | dependency install + baseline, *before any agent code runs* |
| **AGENT** | per-run `internal: true` network + relay | no default route → general egress dead |

> **Corrected 2026-08-11.** This note previously claimed the proxy stays reachable via `host.docker.internal` and a host-gateway mapping. **That is false.** A container on an `internal: true` network has no default route *at all* — not to the internet and not to the host gateway. Measured: the proxy answered `200` before `seal()` and was unreachable after. Because `seal()` only verified that egress was dead, every sandboxed run made **zero model requests and still reported success**.

### The relay

The agent reaches the proxy through a per-run **relay container** attached to *both* the run's internal network and the default bridge:

```
agent (internal net only)  →  aso-relay-<run>  →  host.docker.internal:8005  →  proxy
```

The agent still has exactly one reachable destination and no route to the internet. Verified after sealing: direct `host.docker.internal` **unreachable**, via relay **200 OK**, external egress **refused**.

**`seal()` now fails closed in both directions.** It asserts external egress is dead *and* the proxy is reachable, raising if either check fails. Verifying only the first is what let a run look successful while doing nothing.

Cleanup removes the agent, the relay, then the network — in that order, since a network with live endpoints refuses removal and would leak on every run.

## The harness runs inside

Both mini-SWE-agent and (planned) smolagents are installed **in the sandbox image**, not on the host, so their shell commands are jailed and their only network path is the proxy. Image: `sandbox-images/python/Dockerfile` → `aso-sandbox-python:dev`.

This constraint is why OpenHands is hard — it normally spawns its *own* Docker runtime, which needs a socket we deliberately do not mount. See [[ADR-001 Harness Choice]].

It is also why a repo's own Dockerfile is never built: its `FROM` would discard the harnesses along with the sandbox user and git config. A repo Dockerfile is *read* for the packages it apt-installs, as evidence for the per-repo layer below, and nothing more.

## The per-repo layer

`sandboxes/environment.py` resolves what a repo needs before its own install command can run — system packages from a **fixed allowlist**, plus the manifests and build files to copy. `prepared.py` turns that into one cached image per repo.

Two properties are easy to get wrong, and both were:

- **Search one directory deep, and preserve paths.** Manifests were found root-only and copied flattened to their basename, so a repo keeping `backend/pyproject.toml` contributed *nothing* to the build context and `cd backend && uv sync` could never work. `Eval-Personalised-Harness` failed with a 138-byte context — the generated Dockerfile alone.
- **Only cache what the mount cannot hide.** Containers bind-mount the host workspace over `/workspace`. `pip install` populates site-packages and survives; `uv sync` and `npm install` write `.venv` and `node_modules` *inside* the project and are erased the moment the container starts. For those the image build is skipped entirely and the install runs in-container instead — see `installs_into_workspace`.

A failed install no longer ends the baseline. It names the missing tool, warns, and lets the test step decide whether there is a signal: plenty of repos are stdlib-only and score fine with no install at all.

## Honest security limitation

Local Docker sandboxing is appropriate for **trusted** MVP testing. It is *not* hardened multi-tenant isolation: containers share the host kernel, evaluation commands currently run on the host, and the backend is unauthenticated localhost.

> Do not point this at untrusted repositories you would not run on your machine.

§31 forbids claiming otherwise.

## Related

- [[Leakage Prevention]] · [[Model Proxy]] · [[Run Lifecycle]] · [[ADR-001 Harness Choice]]
