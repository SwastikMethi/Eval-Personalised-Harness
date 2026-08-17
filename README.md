# Agent Stack Optimizer

Benchmark **coding-agent harness × open-weight model × config** against tasks from **your own repository**, then get best-quality / best-reliability / best-efficiency / best-balanced recommendations. Local, single-user.

The question is not "which model is best" — it is *for this repository and these tasks, which harness-model pairing gives the best quality, reliability and efficiency at the lowest practical cost?* A model that tops a public leaderboard can still lose here because the harness around it drives it badly.

Spec: `generationDoc.md` (unchanged). Architecture and decisions: `vault/` (Obsidian, source of truth) and `docs/architecture.md`.

## What it does

1. **Repository** — point it at a local path or public GitHub URL. Languages, package managers and test commands are detected; a clean baseline runs before any agent touches the repo, so pre-existing failures are never blamed on an agent.
2. **Tasks** — three kinds, and they are not interchangeable:
   - *Replay a commit* — the parent becomes the starting state and the commit is the known answer. The strongest signal, because the real tests shipped with the fix.
   - *Understand the code* — comprehension questions graded against a rubric written from the repository. No test suite, no patch, no dependency install, so this is the only mode that works on a repo whose own tests cannot distinguish a correct patch from an empty one.
   - *Describe a task* — your own prompt.
3. **Agent stacks** — each stack is one harness against one model on one provider. Pick exactly the pairings you want; a matrix may mix providers.
4. **Review** — the expanded run count, the model-request budget against the free-tier daily cap, and every blocker, before anything is spent.
5. **Live / Results** — per-run progress, then a single ranked recommendation with the caveats that qualify it.

Ships with **mini-swe-agent**, **smolagents**, and a **fake** harness for zero-cost demos.

Benchmark providers are **OpenRouter** and **NVIDIA NIM**; spec §2 scopes the subjects to open-weight stacks. OpenAI and Anthropic are wired in separately as the repository *analyzer* — the model that reads the code, shortlists commits and writes rubrics — and are never benchmarked themselves.

## Status

All seven build stages are complete: foundation and walking skeleton, repository analysis and baseline, hardened provider proxy, Docker sandbox with mini-swe-agent, task replay and evaluation, results and recommendations, and docs. smolagents landed after those, and the frontend was rebuilt without a component library.

Current state, known defects and what is next live in the vault rather than here, because a status list in two places is a status list that disagrees with itself:

- `vault/03-status/Known Defects.md`
- `vault/04-plan/Roadmap.md`
- `vault/01-product/Acceptance Criteria.md`

Still open: OpenHands (it wants its own Docker runtime, which needs a socket we will not mount), PR replay, and Compose packaging. See `TODOS.md`.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, Docker, macOS/Linux.

```sh
make setup            # backend deps (uv sync) + frontend deps (npm install)
make sandbox-image    # build aso-sandbox-python:dev — required before any real run
cp .env.example .env  # add OPENROUTER_API_KEY (and NVIDIA_API_KEY / OPENAI_API_KEY if used)
make dev              # backend :8005 (native host process) + frontend :3000
make test             # backend pytest + frontend vitest
make demo             # end-to-end fake experiment, zero API cost
```

`make sandbox-image` is not automatic and nothing reruns it for you. A stale image shows up inside a container as `command not found`, which points at the repo rather than at the image — rebuild after editing `sandbox-images/python/Dockerfile`.

The backend runs natively on the host, not in a container, so it can manage sibling sandbox containers without socket mounts or path translation (`vault/05-decisions/ADR-004 Backend on Host.md`). Mounting a Docker socket into a sandbox is a hard no — see Security below.

### Free-tier reality

The OpenRouter free tier allows roughly **50 model requests per day**. Quota, not engineering speed, sets the pace of real runs.

- Develop against `FakeProvider`. The full test suite and `make demo` cost nothing.
- `max_model_requests` defaults to **8** per run so a six-run smoke test fits in one day.
- Runs that hit a rate limit are parked and resume with backoff — the matrix takes longer rather than failing.

## How a repository gets its environment

Dependencies are installed once per repository into a cached image rather than once per run, keyed by a content hash of the manifests and the resolved package set.

- Manifests and build files are discovered **one directory deep** with their paths preserved, so a monorepo keeping `backend/pyproject.toml` and `frontend/package.json` works.
- System packages come from a **fixed allowlist** (`sandboxes/environment.py`). A repository's own `Dockerfile`, if present, is *read* for the packages it installs — it is never built, because its `FROM` would discard the harnesses that live inside our image.
- Installers that write **inside** the project (`uv sync`, `npm install`) are not baked in: every container bind-mounts the workspace over `/workspace`, which would erase them. Those run in-container instead.
- If an install cannot run, the baseline names the missing tool and still attempts the suite. Plenty of repositories are stdlib-only and score fine without one.

## Measurement honesty

These are invariants, not preferences. Breaking one produces a number that looks like a result and is not.

- Unavailable metrics are `null`, never inferred. Token counts come from the provider.
- `INSUFFICIENT_EVALUATION_SIGNAL` is a valid outcome, and so is "no winner" — a tie is reported as a tie.
- Efficiency is gated behind correctness, so fast-but-wrong never ranks well.
- An empty patch or a failed run is a legitimate benchmark result, not a bug to paper over.
- Fewer than three repetitions is flagged **statistically weak**; no significance is claimed from a small experiment.
- Judged scores are counted from rubric hits, never taken from the model, and the judge cannot be pinned to temperature 0 — results say so.

## Security

- The agent container never receives a provider API key, only a short-lived per-run token.
- Sandboxes are sealed after a PREP phase and **fail closed**: if the egress probe succeeds, the run refuses to start.
- The sandbox never contains the solution commit, the final patch, hidden tests, future history, or a remote that could fetch the answer.
- No `docker.sock` is mounted into a sandbox. A harness that requires one does not ship.
- Local Docker sandboxing suits trusted testing. It is **not** hardened isolation against hostile code — do not point this at a repository you would not run on your machine.

## Layout

```
backend/app/     api · core · db · models · providers · harnesses ·
                 sandboxes · repositories · tasks · evaluators ·
                 orchestration · scoring
frontend/src/    React + TS + Vite. design/ tokens, ui/ primitives, motion.
sandbox-images/  Docker image the agents run inside
fixtures/        python-bug-repo demo fixture
vault/           Obsidian knowledge base — architecture, decisions, defects
docs/            architecture.md, implementation-plan.md
data/            SQLite + run artifacts (gitignored)
```

The frontend has no component library: `design/tokens.ts` holds the palette and scale, `ui/` holds the primitives, and `motion` drives state transitions. Colour is semantic and never ornamental — cyan is running, green passed, amber degraded, red failed.
