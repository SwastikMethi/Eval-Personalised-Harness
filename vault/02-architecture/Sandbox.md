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
| **AGENT** | per-run `internal: true` network | no default route → general egress dead |

The proxy remains reachable because the container is created with an `extra_hosts` host-gateway mapping and the proxy URL uses `host.docker.internal` — reaching the *host* gateway does not require a routable external network.

**`seal()` fails closed.** After switching networks it probes external egress; if the probe succeeds, it cleans up and raises rather than proceeding. A sandbox that cannot prove it is sealed is not used.

## The harness runs inside

Both mini-SWE-agent and (planned) smolagents are installed **in the sandbox image**, not on the host, so their shell commands are jailed and their only network path is the proxy. Image: `sandbox-images/python/Dockerfile` → `aso-sandbox-python:dev`.

This constraint is why OpenHands is hard — it normally spawns its *own* Docker runtime, which needs a socket we deliberately do not mount. See [[ADR-001 Harness Choice]].

## Honest security limitation

Local Docker sandboxing is appropriate for **trusted** MVP testing. It is *not* hardened multi-tenant isolation: containers share the host kernel, evaluation commands currently run on the host, and the backend is unauthenticated localhost.

> Do not point this at untrusted repositories you would not run on your machine.

§31 forbids claiming otherwise.

## Related

- [[Leakage Prevention]] · [[Model Proxy]] · [[Run Lifecycle]] · [[ADR-001 Harness Choice]]
