# Agent Stack Optimizer — working instructions

Local, single-user platform that benchmarks **coding-agent harness × open-weight model × config** against real tasks from a user's own Git repository, then recommends the best quality / reliability / efficiency / balanced stack.

Central question: *for this repository and these coding tasks, which harness-model combination gives the best quality, reliability, and efficiency at the lowest practical cost?* This is **not a model leaderboard** — it evaluates the complete stack.

---

## 1. Read the vault before acting

`vault/` is an Obsidian vault and the **source of truth** for architecture, status, decisions, and plan. `generationDoc.md` is the original spec, preserved unchanged — read it for spec questions, but the vault reflects what is actually true today.

Start at `vault/00 Index.md`. Before any non-trivial change, read the relevant note:

| Working on… | Read first |
|---|---|
| The run pipeline / queue | `02-architecture/Run Lifecycle.md` |
| Workspaces, snapshots, replay | `02-architecture/Leakage Prevention.md` |
| Model access, tokens, budgets | `02-architecture/Model Proxy.md` |
| Containers, network sealing | `02-architecture/Sandbox.md` |
| Grading a patch | `02-architecture/Evaluation Engine.md` |
| Weights, ranking, recommendations | `02-architecture/Scoring and Ranking.md` |
| What to build next | `04-plan/Roadmap.md` |
| Why something is the way it is | `05-decisions/` |
| Finding a file | `06-reference/Codebase Map.md` |

### Using the Obsidian CLI

`obsidian` (v1.13.4) is installed. It drives the **running Obsidian app**, so the app must be open with this vault registered (`obsidian vaults` to check).

```sh
obsidian search:context query="leakage" path=vault    # search with matching lines
obsidian read file="Known Defects"                    # read a note by name
obsidian files folder=vault/02-architecture           # list notes in a folder
obsidian backlinks file="Model Proxy"                 # what links here
obsidian links file="Roadmap"                         # what this links to
obsidian tags counts                                  # tag overview
```

**Fallback:** notes are plain markdown on disk. If Obsidian is not running, use Grep/Read on `vault/` — always valid, never blocked.

### Keep the vault current

When work lands, update the affected note **in the same change**:
- `03-status/Known Defects.md` — strike a defect when it is genuinely fixed
- `01-product/Acceptance Criteria.md` — update the live tally
- `04-plan/Roadmap.md` — mark the phase
- `99-log/Session Log.md` — append what changed and why

A stale vault is worse than no vault.

---

## 2. Locked decisions

Do not relitigate these without a new ADR:

| Decision | Choice | ADR |
|---|---|---|
| Harness order | smolagents next; **OpenHands last** | ADR-001 |
| Models | `nvidia/nemotron-3-ultra-550b-a55b:free`, `openai/gpt-oss-20b:free`, `cohere/north-mini-code:free` | ADR-002 |
| Scope | Full spec, no deferrals | — |
| First matrix | 6 runs (2 harnesses × 3 models × 1 task × 1 rep), then scale | — |
| Backend | Native host process on **port 8005**, not containerized | ADR-004 |

---

## 3. The quota constraint — read before any real run

The OpenRouter account is **free tier with no credits**: ~20 requests/minute, ~**50 free-model requests per day**.

- **Develop and test against `FakeProvider`.** The full test suite and `make demo` cost zero quota.
- **Spend real quota only on milestone runs.** Burning the daily cap on a debugging loop costs a day of wall-clock.
- `max_model_requests` defaults to **8** per run so a 6-run smoke fits one day.
- Quota, not engineering speed, sets the schedule. See `05-decisions/ADR-003 Free Tier Constraints.md`.

---

## 4. Invariants — never break these

**Security**
- The agent container **never** receives the OpenRouter API key — only a short-lived per-run token.
- The sandbox **never** contains the solution commit, the final patch, hidden tests, future history, or remotes that could fetch the answer.
- Sandbox network sealing **fails closed**: if the egress probe succeeds, refuse to run.
- **No `docker.sock` mount** into sandboxes. If a harness needs one, that harness does not ship — document the constraint instead of weakening isolation.
- Never log, echo, or return secrets. Never render them in the UI.

**Measurement honesty**
- **Do not fake metrics.** Mark unavailable metrics `null`. Never infer token counts from string length when the provider reports usage.
- **Do not produce a winner from weak evaluation signal.** `INSUFFICIENT_EVALUATION_SIGNAL` is a valid outcome.
- **Do not let a fast-but-wrong run rank high.** Efficiency is gated behind correctness.
- **Do not use historical-patch similarity** as a correctness metric — diagnostic only, zero weight.
- Do not claim statistical significance from a small experiment.
- Do not claim Docker provides hardened hostile-code isolation.
- Do not expose private chain-of-thought.

An empty patch or a failed run is a **legitimate benchmark result**, not a bug to paper over.

---

## 5. Code quality rules (spec §31)

- Prefer simple, explicit code. Use strong typing.
- Avoid giant service classes.
- Keep provider, harness, sandbox, task, evaluator, and scoring layers **independent**.
- Do not put harness-specific logic in the orchestrator (`queue.py`).
- Do not put provider-specific logic in harness adapters.
- Do not silently swallow exceptions — categorize them.
- Do not add unnecessary infrastructure. No Redis, Celery, Kafka, Kubernetes, or PostgreSQL.
- Match the surrounding style. Touch only what the change requires.

---

## 6. Verification loop

After every phase (spec §29):

```sh
make lint && make typecheck && make test
make demo          # fake harness, zero quota — must stay green
```

Then update the vault (§1) and commit with a meaningful message.

**Known-broken targets** (fixed in Phase 1): `make migrate`, `make seed` both fail; `make test-frontend` is a false green — it runs nothing and exits 0. Do not read a passing `make test` as covering the frontend.

Evidence before assertions: if you claim something passes, show the output.

---

## 7. Layout

```
backend/app/       api · core · db · models · providers · harnesses ·
                   sandboxes · repositories · tasks · evaluators ·
                   orchestration · scoring
frontend/src/      React + TS + Vite + MUI dashboard
sandbox-images/    Docker images the agents run inside
fixtures/          python-bug-repo demo fixture
vault/             Obsidian knowledge base — source of truth
data/              SQLite + run artifacts (gitignored)
generationDoc.md   Original spec, unchanged
```
