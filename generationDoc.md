You are a senior staff engineer and AI evaluation researcher. Build a production-quality local MVP of an **Agent Stack Optimizer for coding tasks**.

Do not only generate a design document. Create the working application, source code, database models, Docker configuration, tests, documentation, example data, and setup scripts.

Work incrementally. Inspect the repository before making decisions. Keep the application runnable after every major phase. Do not leave core functionality as pseudocode.

# 1. Product goal

Build a platform that evaluates combinations of:

* Coding-agent harness
* Open-weight coding model served through an API
* Agent configuration

against real tasks from a user-selected Git repository.

The platform must determine which harness-model combination provides the best balance of:

* Correctness
* Reliability
* Execution efficiency
* Token efficiency
* Estimated cost
* Developer productivity

The first version is local-only and single-user.

The central product question is:

> For this repository and these coding tasks, which harness-model combination gives the best quality, reliability, and efficiency at the lowest practical cost?

This is not merely a model leaderboard. It evaluates the complete agent stack.

# 2. Strict MVP scope

Implement only:

* Coding-related repository tasks
* One repository per experiment
* Local Git repositories and public GitHub repository URLs
* Three open-source coding harnesses
* Three selectable open-weight coding models
* OpenRouter as the first hosted inference provider
* Free OpenRouter model variants where available
* Local Docker sandboxing
* Existing-test evaluation
* Historical commit replay
* Historical PR replay when GitHub metadata is available
* Sequential or limited-concurrency execution
* Metrics collection
* Side-by-side comparison
* Recommendation generation
* Local single-user dashboard

Do not implement:

* Authentication
* Multi-tenancy
* Billing
* Teams or organizations
* Cloud sandbox infrastructure
* Kubernetes
* Research or browser benchmarks
* A public benchmark marketplace
* Fine-tuning
* Training models
* Support for closed-source paid models
* Complex distributed infrastructure

Create extension points for these features, but do not implement them now.

# 3. Initial harnesses

Integrate these harnesses behind a common adapter interface:

1. OpenHands Software Agent SDK
2. mini-SWE-agent
3. Hugging Face smolagents CodeAgent

Use current supported APIs from their official documentation.

Pin compatible dependency versions. Do not guess imports or APIs. If a harness cannot be integrated directly because of a current SDK limitation, create a subprocess adapter using its supported CLI, but preserve the same normalized interface and telemetry contract.

Each harness adapter must support:

* Preparation
* Execution
* Cancellation
* Timeout
* Log streaming
* Final output collection
* Patch collection
* Token-usage collection where available
* Tool/action trajectory collection
* Error normalization
* Cleanup

Use an interface similar to:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass
class HarnessRunRequest:
    task_id: str
    task_prompt: str
    workspace_path: Path
    model_id: str
    provider: str
    timeout_seconds: int
    max_steps: int
    temperature: float
    metadata: dict


@dataclass
class HarnessRunResult:
    status: str
    final_message: str | None
    patch: str | None
    started_at: str
    completed_at: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    model_requests: int
    agent_steps: int
    tool_calls: int
    commands_executed: int
    error_type: str | None
    error_message: str | None
    raw_metadata: dict


class HarnessAdapter(ABC):
    @abstractmethod
    async def validate_configuration(self) -> list[str]:
        pass

    @abstractmethod
    async def prepare(self, request: HarnessRunRequest) -> None:
        pass

    @abstractmethod
    async def run(
        self,
        request: HarnessRunRequest,
    ) -> HarnessRunResult:
        pass

    @abstractmethod
    async def stream_events(
        self,
        run_id: str,
    ) -> AsyncIterator[dict]:
        pass

    @abstractmethod
    async def cancel(self, run_id: str) -> None:
        pass

    @abstractmethod
    async def cleanup(self, run_id: str) -> None:
        pass
```

Modify the exact interface when necessary, but all harnesses must produce the same normalized result.

# 4. Model-provider architecture

Implement a provider abstraction.

The MVP provider is OpenRouter using its OpenAI-compatible API.

The design must later allow:

* Ollama
* vLLM
* llama.cpp
* Groq
* Hugging Face inference providers
* Any OpenAI-compatible endpoint

Use an interface similar to:

```python
@dataclass
class ModelInfo:
    provider: str
    model_id: str
    display_name: str
    context_length: int | None
    supports_tools: bool
    supports_structured_output: bool
    input_price_per_token: float
    output_price_per_token: float
    is_free: bool
    availability_status: str


class ModelProvider(ABC):
    async def list_models(self) -> list[ModelInfo]:
        ...

    async def validate_model(self, model_id: str) -> ModelInfo:
        ...

    async def test_connection(self) -> dict:
        ...

    async def get_rate_limit_state(self) -> dict:
        ...
```

Important rules:

* Never use `openrouter/free` for controlled benchmark experiments because it can route requests to different underlying models.
* Query OpenRouter's model listing endpoint.
* Identify exact free model variants using pricing metadata and/or the `:free` suffix.
* Let the user choose and pin exactly three model IDs.
* Save the exact model ID and model metadata with every experiment.
* Validate that a selected model supports the capabilities needed by a harness.
* Display warnings for uncertain tool-calling compatibility.
* Never silently replace a selected model.
* If a model becomes unavailable, fail that combination clearly.
* Handle HTTP 402, 429, 5xx, timeout, invalid response, and context-limit errors.
* Record provider rate-limit headers when available.
* Do not expose the OpenRouter API key in logs, frontend responses, sandbox environment dumps, or database exports.

Use these environment variables:

```env
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_HTTP_REFERER=http://localhost:3000
OPENROUTER_APP_NAME=Agent Stack Optimizer
```

Provide `.env.example`, never commit real credentials.

# 5. Technology stack

Use:

## Backend

* Python 3.12
* FastAPI
* SQLAlchemy 2
* Alembic
* Pydantic 2
* SQLite for the MVP
* Async APIs where useful
* Structured JSON logging
* Server-Sent Events or WebSockets for live run updates
* psutil for host/container process metrics where appropriate
* Docker SDK for Python or safe Docker CLI subprocess calls

## Frontend

* React
* TypeScript
* Vite
* Material UI
* TanStack Query
* React Router
* Recharts for result visualizations

## Execution

* Docker Engine on the local machine
* One fresh container per benchmark run
* Local job queue implemented in the backend
* Configurable concurrency, default 1

## Development

* Docker Compose
* Ruff
* mypy
* pytest
* pytest-asyncio
* ESLint
* Prettier
* Vitest
* Playwright for a small end-to-end smoke test

Do not add Redis, Celery, Kafka, Kubernetes, or PostgreSQL for the MVP.

# 6. Repository onboarding

Support:

* Local repository path
* Public GitHub repository URL
* Optional GitHub token for reading PR metadata from private repositories later

For the MVP, private repository cloning may be implemented only when a token is explicitly supplied through backend configuration. Never persist the token in plaintext.

Analyze the repository and detect:

* Primary languages
* Package managers
* Dependency files
* Build commands
* Test frameworks
* Test commands
* Test locations
* Lint commands
* Type-check commands
* CI workflow files
* Dockerfiles
* Required runtime versions
* Repository size
* Default branch
* Current commit
* Recent commits
* Potential candidate tasks

Do not only search for a folder named `tests`.

Detect common patterns including:

```text
tests/
test/
spec/
__tests__/
*.test.*
*.spec.*
pytest.ini
pyproject.toml
tox.ini
package.json scripts
go test
Cargo.toml
pom.xml
build.gradle
Makefile
GitHub Actions workflows
```

Build a repository analyzer using pluggable language detectors.

Initially provide strong support for:

* Python repositories
* JavaScript/TypeScript repositories

Other languages can be reported as detected but unsupported.

After analysis, show the detected commands to the user and allow manual editing before an experiment begins.

# 7. Baseline validation

Before evaluating agents:

1. Create a clean baseline sandbox.
2. Check out the selected base commit.
3. Install dependencies using the configured command.
4. Run the build command when configured.
5. Run existing tests.
6. Run lint/type checking when configured.
7. Record baseline failures and durations.
8. Confirm whether the repository is benchmarkable.

Never count failures already present at the base commit as regressions introduced by an agent.

Store:

* Baseline build result
* Baseline test total
* Baseline passed tests
* Baseline failed tests
* Baseline skipped tests
* Baseline command output
* Baseline duration
* Baseline lint/type-check results

Allow the user to proceed with a warning when the baseline is partially failing.

# 8. Task sources

Implement two primary benchmark task modes.

## 8.1 User-defined task

The user provides:

* Base branch or commit
* Task title
* Task description
* Optional acceptance criteria
* Optional evaluation command
* Optional expected files

This mode uses existing tests and user-defined checks.

## 8.2 Historical replay

The user selects a historical commit or merged PR.

For a historical commit:

* Identify the parent commit as the base state.
* Treat the selected commit as the known historical solution.
* Build the task description from the commit message.
* Let the user edit the generated task before execution.

For a merged PR when metadata is available:

* Use the commit immediately before the PR changes as the base.
* Use the PR title and description as the task.
* Store linked issue and review metadata when available.
* Do not expose the final patch to the agent.

For the MVP, require the user to manually select 1–5 historical tasks. Do not attempt fully automatic task mining.

# 9. Hidden evaluation and leakage prevention

Historical replay must prevent answer leakage.

The agent sandbox must not contain:

* The target solution commit
* The final historical patch
* Hidden tests
* Future repository history
* Remote Git configuration that enables fetching the answer
* GitHub PR diff URLs
* Unrestricted internet access

Create a clean repository snapshot containing the base state only.

Recommended approach:

1. On the host, create an archive of the repository at the base commit.
2. Extract the archive into a fresh sandbox workspace.
3. Initialize a new Git repository in the workspace.
4. Make one synthetic baseline commit.
5. Do not copy `.git` history from the original repository.
6. Disable network access for agent containers by default.
7. Connect only the model API through a controlled host-side proxy or restricted network path.

The final historical implementation may be available only to the evaluator outside the agent sandbox.

# 10. Existing and hidden tests

Use three categories:

## Visible tests

Tests that existed at the base commit. The agent may inspect and run them.

## Hidden tests

Tests introduced by the historical target change, when they can be safely separated from implementation changes.

The agent must not see hidden tests before finishing.

After the agent stops:

1. Copy eligible hidden test files into the completed workspace.
2. Run them without allowing the agent to continue editing.
3. Store hidden-test results separately.

## Regression tests

Run the full base test suite after the agent's patch.

Implement a conservative hidden-test extractor:

* Compare test files between base and target commits.
* Detect newly added or modified test files.
* Copy only test-related changes.
* Reject hidden tests that import implementation files that exist only in the historical target but not in the agent result unless that behavior is intentional.
* Mark extraction confidence.
* Allow the user to inspect and enable or disable candidate hidden tests before running an experiment.

Never automatically claim generated or extracted tests are trustworthy. Record their provenance.

# 11. Repositories without tests

Use this fallback order:

1. Tests added by the historical commit or PR
2. Build and static-analysis checks
3. User-defined evaluation commands
4. Differential behavior checks
5. Automatically generated tests as an experimental fallback
6. Reviewer-model evaluation only as a low-weight supplemental signal

For the first working version, fully implement items 1–3.

Create interfaces and clear TODO documentation for differential testing and generated-test workflows, but do not pretend they are complete.

If no meaningful deterministic evaluator exists, mark the task:

```text
INSUFFICIENT_EVALUATION_SIGNAL
```

Do not produce a high-confidence winner from weak evaluation.

# 12. Sandbox execution

Use Docker locally.

Each run gets:

* Fresh container
* Fresh repository snapshot
* Non-root user
* Dedicated writable workspace
* CPU limit
* Memory limit
* PID limit
* Wall-clock timeout
* No privileged mode
* No host Docker socket
* No host filesystem mounts except the prepared workspace and required read-only configuration
* Restricted or disabled network
* Automatic cleanup
* Captured stdout and stderr
* Captured container exit state

Default limits:

```yaml
cpu_limit: 2
memory_limit_mb: 4096
pids_limit: 256
timeout_seconds: 1800
network_mode: restricted
max_output_bytes: 10000000
```

Make these configurable per experiment.

Because models are accessed through OpenRouter, implement a controlled inference proxy in the backend or a narrowly scoped network setup. Agent containers must not receive the raw OpenRouter API key.

Preferred design:

```text
Sandbox harness
    |
    | OpenAI-compatible request with short-lived internal token
    v
Local model proxy in backend
    |
    | Real OpenRouter API key
    v
OpenRouter
```

The internal proxy must:

* Validate the run ID
* Allow only the pinned model for that run
* Enforce maximum requests and token budgets
* Record usage and latency
* Reject arbitrary external destinations
* Expire run tokens after completion
* Redact secrets
* Persist normalized request metadata without storing private chain-of-thought

Do not log hidden reasoning. Store only observable messages, actions, tool calls, responses, usage data, and errors that the harness exposes for legitimate telemetry.

# 13. Job queue and orchestration

An experiment consists of:

```text
tasks × harnesses × models × repetitions
```

Default repetitions: 3.

Before starting, display the number of expected runs.

Implement a local persistent queue with states:

```text
PENDING
PREPARING
RUNNING
EVALUATING
COMPLETED
FAILED
CANCELLED
TIMED_OUT
RATE_LIMITED
```

Requirements:

* Default concurrency of 1
* Configurable maximum concurrency
* Pause experiment
* Resume experiment
* Cancel queued run
* Cancel active run
* Retry failed run
* Recover queued experiment state after backend restart
* Never accidentally execute the same run twice
* Use idempotency keys
* Persist state transitions
* Record failure categories

Use an asyncio-based worker service within the backend process for the MVP, but isolate queue logic behind an interface for future replacement.

# 14. Telemetry

Collect normalized metrics for every run.

## Model metrics

* Exact provider
* Exact model ID
* Input tokens
* Output tokens
* Cached tokens when reported
* Total tokens
* Number of model requests
* Request latency
* Time to first token when available
* Rate-limit responses
* Context-limit failures
* Estimated API cost
* Actual reported API cost when available

Free models should normally show:

```text
API cost: $0.00
```

but still record tokens and usage.

## Harness metrics

* Agent steps
* Tool calls
* Commands executed
* Failed commands
* Repeated commands
* Files read when observable
* Files modified
* Lines added
* Lines removed
* Time to first edit
* Time to first test run
* Time to first passing test
* Total harness duration
* Harness error type

## Sandbox metrics

* Wall-clock duration
* CPU time
* Peak memory
* Container exit code
* Timeout
* Process-limit failures
* Disk usage change

## Evaluation metrics

* Build passed
* Existing tests passed
* Existing tests failed
* Hidden tests passed
* Hidden tests failed
* Regression count
* Lint result
* Type-check result
* Patch produced
* Empty-patch status
* Prohibited file modifications
* Evaluation confidence

# 15. Evaluation engine

Create composable evaluators:

```python
class Evaluator(ABC):
    name: str

    @abstractmethod
    async def evaluate(self, context: EvaluationContext) -> EvaluationResult:
        pass
```

Implement:

* BuildEvaluator
* ExistingTestsEvaluator
* HiddenTestsEvaluator
* RegressionEvaluator
* LintEvaluator
* TypeCheckEvaluator
* PatchStatsEvaluator
* ProhibitedFilesEvaluator
* EfficiencyEvaluator
* ReliabilityAggregator

Store raw evaluator results and normalized scores separately.

Do not use textual similarity to the historical patch as the primary correctness metric.

Historical patch similarity may be shown only as optional diagnostic information and must have zero weight in the default score.

# 16. Reliability

Run every combination multiple times.

For each harness-model-task combination calculate:

* Success rate
* Mean score
* Median score
* Standard deviation
* Timeout rate
* Empty-patch rate
* Harness crash rate
* Model-provider failure rate
* Test-result variance

A single lucky run must not dominate the recommendation.

Clearly distinguish:

* Model failure
* Harness failure
* Repository/setup failure
* Provider rate limiting
* Evaluation failure
* Agent-produced incorrect solution

# 17. Ranking and recommendation

Do not hide all results behind one score.

First apply eligibility rules.

A combination is ineligible for the balanced recommendation when:

* It never produces a patch
* Build success is required and it consistently fails
* It introduces critical regressions
* Hidden-test performance is below the configured threshold
* More than half its runs time out
* Evaluation signal is insufficient
* Fewer than the configured minimum number of repetitions complete

For eligible combinations calculate default normalized dimensions:

```text
Correctness: 50%
Reliability: 20%
Execution efficiency: 15%
Token efficiency: 10%
Resource efficiency: 5%
```

Normalize efficiency only among comparable runs for the same task.

Avoid rewarding a combination merely because it stopped early without completing the task.

Generate:

1. Best quality
2. Best reliability
3. Best efficiency
4. Best balanced combination

For each recommendation show:

* Why it won
* Trade-offs
* Confidence
* Number of tasks
* Number of completed repetitions
* Correctness score
* Reliability score
* Average duration
* Average tokens
* Failure rate
* Whether the result is statistically weak

Use Pareto-frontier analysis for correctness versus tokens and correctness versus duration.

Do not claim statistical significance from a very small experiment.

# 18. Database design

Create SQLAlchemy models and Alembic migrations for at least:

* Repository
* RepositoryAnalysis
* RepositoryCommand
* BenchmarkTask
* HistoricalTaskMetadata
* HiddenTestCandidate
* ModelProviderConfiguration
* ModelSnapshot
* HarnessDefinition
* Experiment
* ExperimentCombination
* BenchmarkRun
* RunEvent
* ModelRequestMetric
* HarnessMetric
* SandboxMetric
* EvaluationResult
* Artifact
* Recommendation

Store large logs and patches as files under an application data directory, with paths and checksums in the database.

Do not store large logs directly in SQLite.

# 19. API

Implement REST APIs for:

## Repositories

* Add local repository
* Clone public repository
* Analyze repository
* Get analysis
* Update detected commands
* List historical commits
* Fetch PR metadata when possible

## Providers and models

* Test OpenRouter connection
* List eligible free models
* Get model details
* Validate selected model
* Snapshot selected model metadata

## Tasks

* Create user-defined task
* Create task from commit
* Create task from PR
* List hidden-test candidates
* Approve or reject hidden-test candidates

## Experiments

* Create experiment
* Preview run matrix
* Start experiment
* Pause experiment
* Resume experiment
* Cancel experiment
* Retry run
* Get experiment status
* Stream experiment events
* Get results
* Get recommendations

## Runs

* Get run summary
* Get run events
* Get logs
* Get patch
* Get evaluator results
* Get resource metrics

Add OpenAPI descriptions and typed frontend clients.

# 20. Frontend screens

Build a simple, minimal, professional interface with neutral colors.

## Dashboard

Show:

* Recent repositories
* Recent experiments
* Running experiment status
* Best recent recommendation
* Failed and rate-limited runs

## Repository onboarding wizard

Steps:

1. Repository source
2. Repository analysis
3. Detected commands
4. Baseline validation
5. Task selection

## Task selection

Support:

* User-defined task
* Historical commit
* Historical PR
* Hidden-test candidate review

## Experiment configuration

Allow selection of:

* Exactly three harnesses by default
* Up to three models
* One to five tasks
* Repetitions
* Timeout
* CPU and memory limits
* Maximum model requests
* Maximum tokens
* Temperature
* Concurrency
* Scoring weights

Show the expanded matrix:

```text
3 harnesses × 3 models × 3 tasks × 3 repetitions = 81 runs
```

## Live experiment screen

Show:

* Overall progress
* Queue
* Active run
* Run state
* Harness
* Model
* Task
* Elapsed time
* Model requests
* Tokens
* Recent observable actions
* Rate-limit warnings
* Cancel controls

## Results screen

Show:

* Comparison table
* Best-quality card
* Best-reliability card
* Best-efficiency card
* Best-balanced card
* Correctness versus tokens chart
* Correctness versus time chart
* Reliability chart
* Per-task breakdown
* Failure-reason breakdown
* Run-to-run variance
* Model comparison
* Harness comparison
* Pareto frontier

## Run-detail screen

Show:

* Configuration
* Status timeline
* Patch
* Files changed
* Build results
* Existing tests
* Hidden tests
* Lint/type checking
* Token usage
* Commands
* Logs
* Errors
* Resource metrics

Never render secrets.

# 21. Harness compatibility validation

Create a compatibility-check subsystem.

For every harness-model pair check:

* OpenAI-compatible endpoint support
* Tool-calling support
* Structured-output support
* Context length
* Required prompt/action parser
* Maximum token configuration
* Harness-specific provider syntax
* Known unsupported combinations

Allow uncertain combinations with a warning, but require explicit user acknowledgement.

Add a lightweight preflight test:

1. Start the harness.
2. Ask it to inspect a tiny fixture repository.
3. Ask it to modify one file.
4. Verify the expected patch.
5. Record compatibility status.

Run preflight checks before a full experiment.

# 22. Fixtures and demo

Include a small fixture repository inside the project for development and demonstration.

Create a Python FastAPI sample repository with:

* A small bug
* Existing tests
* One historical-like task
* A hidden test
* A deterministic expected behavior

Also create a TypeScript fixture if time permits.

Provide a demo seed command that creates:

* Repository record
* Repository analysis
* Two benchmark tasks
* Example experiment configuration

The application must be demonstrable without using the user's real repository.

# 23. Security

Implement:

* Secret redaction
* No API keys in sandbox environments
* No API keys in frontend state
* Restricted sandbox network
* No Docker socket mount
* Non-root containers
* Command timeout
* Output-size limits
* Safe path validation
* Prevention of `../` traversal
* Repository size limit
* Log sanitization
* Model proxy authorization
* Per-run internal tokens
* Automatic sandbox cleanup
* No execution on arbitrary host paths without explicit allowlisting

Display a warning that local Docker sandboxing is appropriate for trusted MVP testing but should not be treated as hardened multi-tenant isolation.

# 24. Testing

Write meaningful tests.

Backend:

* Unit tests for repository detection
* Unit tests for command detection
* Unit tests for scoring
* Unit tests for reliability aggregation
* Unit tests for model filtering
* Unit tests for provider-error normalization
* Unit tests for leakage prevention
* Unit tests for hidden-test candidate extraction
* Unit tests for state transitions
* Integration tests for experiment creation
* Integration tests for queue execution using fake harnesses
* Integration test for inference proxy using a mock provider
* Integration test for Docker sandbox using the fixture repository when Docker is available

Frontend:

* Component tests for configuration matrix
* Component tests for result cards
* Component tests for failure states
* API mocking tests
* One Playwright smoke test covering:
  repository selection → task selection → experiment creation → mocked completion → results

Create fake model and fake harness adapters so the full application can be tested without consuming API requests.

# 25. Observability

Use structured JSON logs with:

* request_id
* experiment_id
* run_id
* task_id
* harness
* model_id
* event_type
* duration
* error_category

Provide health endpoints:

```text
GET /api/v1/health
GET /api/v1/ready
```

Provide a diagnostics page showing:

* Docker availability
* OpenRouter connectivity
* Database state
* Harness installation status
* Queue status
* Data-directory permissions

# 26. Project structure

Use a clean monorepo similar to:

```text
agent-stack-optimizer/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── providers/
│   │   ├── harnesses/
│   │   ├── sandboxes/
│   │   ├── tasks/
│   │   ├── evaluators/
│   │   ├── orchestration/
│   │   ├── scoring/
│   │   ├── telemetry/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   ├── tests/
│   ├── package.json
│   └── Dockerfile
├── sandbox-images/
│   ├── python/
│   └── node/
├── fixtures/
│   ├── python-bug-repo/
│   └── typescript-bug-repo/
├── scripts/
├── docs/
├── data/
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
└── README.md
```

Adjust only when there is a clear technical reason.

# 27. Documentation

Write:

* README with product description
* Local setup instructions
* Docker requirements
* OpenRouter setup
* How to choose exact free models
* How rate limits affect experiments
* How to add a harness
* How to add a provider
* How to add an evaluator
* How historical replay works
* Leakage-prevention explanation
* Security limitations
* Scoring methodology
* Troubleshooting
* Architecture document
* Data model document
* API overview
* MVP limitations and roadmap

Include diagrams using Mermaid.

# 28. Developer experience

Provide Make targets:

```text
make setup
make dev
make backend
make frontend
make test
make test-backend
make test-frontend
make lint
make typecheck
make migrate
make seed
make demo
make clean-sandboxes
```

The development setup should be straightforward on macOS and Linux with Docker installed.

# 29. Implementation sequence

Follow this order.

## Phase 1: Foundation

* Create monorepo
* Backend
* Frontend
* Database
* Docker Compose
* Health endpoints
* Configuration
* Logging
* Basic dashboard shell

## Phase 2: Repository analysis

* Repository registration
* Clone/local path handling
* Python and Node detection
* Command detection
* Baseline validation
* Historical commit listing

## Phase 3: Provider layer

* OpenRouter provider
* Dynamic free-model discovery
* Exact model pinning
* Error handling
* Model proxy
* Usage telemetry
* Fake provider

## Phase 4: Sandbox and queue

* Docker sandbox manager
* Workspace snapshot creation
* Leakage prevention
* Queue
* State machine
* Cancellation
* Resource limits
* Fake harness

## Phase 5: Harness adapters

* OpenHands
* mini-SWE-agent
* smolagents CodeAgent
* Preflight compatibility
* Normalized telemetry

Implement one harness completely before moving to the next.

## Phase 6: Tasks and evaluation

* User-defined tasks
* Historical commit replay
* PR replay where metadata is available
* Hidden-test candidates
* Evaluators
* Artifact storage

## Phase 7: Experiments

* Matrix creation
* Repetitions
* Execution
* Live events
* Retry
* Pause/resume
* Failure categorization

## Phase 8: Results and recommendations

* Aggregation
* Reliability
* Ranking
* Pareto frontier
* Dashboard results
* Run details

## Phase 9: Hardening

* Tests
* Security review
* Documentation
* Demo fixture
* Error states
* Cleanup scripts

After each phase:

1. Run formatting.
2. Run linting.
3. Run type checking.
4. Run relevant tests.
5. Fix failures before continuing.
6. Update README status.
7. Commit the phase with a meaningful message if Git is available.

# 30. Acceptance criteria

The MVP is complete when:

1. I can start the application locally with documented commands.
2. I can configure an OpenRouter API key.
3. I can fetch available exact free model variants.
4. I can select up to three pinned models.
5. I can add a local or public Git repository.
6. The platform detects Python or JavaScript/TypeScript build and test commands.
7. I can edit detected commands.
8. The platform runs a clean baseline.
9. I can select a historical commit as a task.
10. The agent receives only the base repository snapshot.
11. The final historical patch is not available inside the sandbox.
12. I can select OpenHands, mini-SWE-agent, and smolagents.
13. The application validates harness-model compatibility.
14. Each run executes in a fresh Docker container.
15. Runs are queued with configurable concurrency.
16. Every combination can run multiple repetitions.
17. Existing tests run after the agent completes.
18. Eligible hidden tests can run after completion.
19. The platform records tokens, time, commands, patch statistics, tests, and failures.
20. I can view live progress.
21. I can compare combinations.
22. I receive best-quality, best-reliability, best-efficiency, and best-balanced recommendations.
23. Weak evaluation signal is clearly identified.
24. Provider rate limiting does not crash the experiment.
25. The application includes automated tests and a working fixture demo.

# 31. Quality rules

* Prefer simple, explicit code.
* Use strong typing.
* Avoid giant service classes.
* Keep provider, harness, sandbox, task, evaluator, and scoring layers independent.
* Do not place harness-specific logic in the experiment orchestrator.
* Do not place provider-specific logic in harness adapters unless unavoidable.
* Do not silently swallow exceptions.
* Do not fake metrics.
* Mark unavailable metrics as null.
* Never infer token counts from string length when the provider reports usage.
* Preserve raw provider usage metadata for diagnostics.
* Do not claim Docker provides hardened hostile-code isolation.
* Do not expose private chain-of-thought.
* Do not use the historical patch as the primary correctness score.
* Do not let a fast but incorrect run receive a high ranking.
* Do not generate a winner when evaluation confidence is insufficient.
* Do not add unnecessary infrastructure.

# 32. Initial action

Before coding:

1. Inspect the current directory.
2. Check whether an existing project is present.
3. Read any existing `CLAUDE.md`, README, architecture documents, and configuration.
4. Verify Docker, Python, Node, and Git availability.
5. Create `docs/implementation-plan.md`.
6. Record assumptions and unresolved risks.
7. Produce the planned directory structure.
8. Then begin Phase 1 immediately.

Do not stop after writing the plan. Continue implementing the application.

When a dependency or harness API differs from this prompt, consult its current official documentation, document the discrepancy, and use the current supported interface.

At the end, provide:

* What was built
* How to run it
* What commands were verified
* Test results
* Known limitations
* Which harness integrations are fully functional
* Which integrations need environment-specific setup
* A short suggested next-development phase
