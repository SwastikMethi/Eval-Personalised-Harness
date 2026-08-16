const BASE = '/api/v1'

export interface Experiment {
  id: string
  name: string
  status: string
}

export interface Repository {
  id: string
  name: string
  source: string
  path_or_url: string
}

export interface Harness {
  name: string
  sandboxed: boolean
}

export interface ModelInfo {
  provider: string
  model_id: string
  display_name: string
  context_length: number | null
  /** null = UNKNOWN, not unsupported. NIM's listing does not report capabilities. */
  supports_tools: boolean | null
  is_free: boolean
  /** Moving alias (`~vendor/model`, `-latest`) — never pinnable, excluded by default. */
  is_alias?: boolean
}

export interface ProviderInfo {
  name: string
  configured: boolean
  has_free_tier: boolean
}

export interface Analysis {
  languages: string[]
  package_managers: string[]
  test_locations: string[]
  supported: boolean
  size_bytes: number
  commands: Record<string, string | null>
  default_branch?: string | null
  current_commit?: string | null
}

export interface Commit {
  sha: string
  subject: string
  author: string
  date: string
  parent: string
}

export interface BaselineOutcome {
  baseline_id: string
  base_commit: string
  benchmarkable: boolean
  warn: boolean
  steps: Record<string, { exit_code: number; output?: string }>
  test_case_count: number
}

export interface HiddenTest {
  id: string
  relpath: string
  change_type: string
  confidence: string
  reject_reason: string | null
  approved: boolean | null
}

export interface Provenance {
  provider: string
  model: string
}

export interface Suggestion {
  model_id: string
  provenance: Provenance
  confidence: 'high' | 'low'
  commands: Record<string, string | null>
  rationale: Record<string, string>
  commits: { sha: string; why: string; subject: string; parent: string }[]
  files_read: string[]
}

/** Outcome of repairing the repo's TEST ENVIRONMENT — never its source. An
 *  unapplied result is the normal case for a healthy repo, not an error. */
export interface PrepareTestsResult {
  applied: boolean
  reason: string
  provenance: Provenance
  changed_paths: string[]
  before?: { benchmarkable: boolean; passing: number }
  after?: { benchmarkable: boolean; passing: number }
  patch?: string
}

/** `verified` means PROVEN to fail before the fix and pass after it — not that
 *  the model sounded confident. `evidence` carries the per-case outcomes at
 *  each commit so a rejection can be read rather than taken on trust. */
export interface GeneratedTestReport {
  relpath: string
  verified: boolean
  reject_reason: string | null
  attempts: number
  evidence: Record<string, [string, string][]>
}

/** A comprehension task and the rubric that will grade it. The rubric is
 *  written when the question is, from the same repo digest, and every criterion
 *  cites a path that was checked to exist — so a hallucinated rubric cannot
 *  mark an answer wrong. `dropped` shows the criteria that failed that check. */
export interface ProposedTask {
  id: string
  category: 'architecture' | 'execution_flow' | 'feature_plan'
  title: string
  prompt: string
  /** `depth` is what lets a low score be read: all-structural-met means the
   *  agent skimmed and was honest; all-missed means it did not look. */
  rubric: { criterion: string; evidence: string; depth: string }[]
  dropped: string[]
}

/** `score` is the share of rubric criteria met, counted from the rubric rather
 *  than reported by the model. `invented` lists names the answer claimed exist
 *  in the repo but do not. */
export interface JudgeVerdict {
  score: number | null
  met: string[]
  /** Substantively right but incomplete — scores half. */
  partial: string[]
  missing: string[]
  invented: string[]
  rationale: string
  error: string
}

export interface PrepareTaskResult {
  task_id: string
  title: string
  prompt: string
  prompt_source: 'model' | 'commit-message'
  provenance: Provenance
  generated_test: GeneratedTestReport | null
}

/** A strategy VERIFIED by execution, unlike Suggestion which is advisory.
 *  `attempts` is the rung-by-rung record of what was tried and why it failed,
 *  so an `unbenchmarkable` verdict can be argued with rather than just read. */
export interface StrategyDecision {
  strategy: 'commit_tests' | 'repo_tests' | 'build_only' | 'unbenchmarkable'
  scoreable: boolean
  meaning: string
  warn: boolean
  commands: Record<string, string | null>
  provenance: { provider: string; model: string }
  rationale: Record<string, string>
  attempts: {
    rung: number
    strategy: string
    ok: boolean
    reason: string
    evidence: Record<string, unknown>
  }[]
  commits: { sha: string; why: string; subject: string; parent: string }[]
}

export interface MatrixPreview {
  combinations: number
  runs: number
  expression: string
}

export interface RunRow {
  run_id: string
  harness: string
  model_id: string
  repetition: number
  state: string
  error_category: string | null
  elapsed_s: number | null
  model_requests: number | null
  input_tokens: number | null
  output_tokens: number | null
  rate_limited: boolean
  budget_exhausted: boolean
  score: number | null
  patch_produced: boolean | null
}

export interface Progress {
  experiment_id: string
  total: number
  done: number
  by_state: Record<string, number>
  finished: boolean
  runs: RunRow[]
}

export interface RunDetail {
  id: string
  state: string
  harness: string | null
  model_id: string | null
  repetition: number
  task: { id: string; title: string; prompt: string } | null
  error_category: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  result: Record<string, unknown>
  usage: Record<string, number | boolean>
  evaluation: { signal: string; score: number | null; results: Record<string, any> } | null
  model_requests: {
    http_status: number
    latency_ms: number
    input_tokens: number | null
    output_tokens: number | null
    routed_provider: string | null
    error: string | null
  }[]
  timeline: { type: string; payload: Record<string, unknown>; at: string }[]
  has_patch: boolean
}

export interface ComboRecommendation {
  harness: string
  model_id: string
  tasks: number
  completed_reps: number
  correctness: number
  reliability: number
  efficiency: number
  balanced: number
  avg_duration_s: number | null
  avg_tokens: number | null
  failure_rate: number
  statistically_weak: boolean
  /** True when nothing scored above zero, or when the leaders are too close to
   *  separate. The entry still carries the top row's numbers, but naming it a
   *  winner would be false precision — read `why`. */
  tied?: boolean
  why?: string
}

export interface CombinationStats {
  combination_id: string
  harness: string
  model_id: string
  task_id: string
  runs: number
  completed: number
  success_rate: number
  mean_score: number | null
  stdev_score: number | null
  timeout_rate: number
  empty_patch_rate: number
  crash_rate: number
  mean_duration_s: number | null
  mean_tokens: number | null
  eligible: boolean
  ineligible_reasons: string[]
  statistically_weak: boolean
  weighted_score: number | null
  components?: Record<string, number>
}

export interface ExperimentResults {
  combinations: CombinationStats[]
  recommendations: Record<string, ComboRecommendation>
  pareto: { correctness_vs_tokens: string[]; correctness_vs_duration: string[] }
  caveats?: string[]
}

export interface ExperimentStatus {
  id: string
  name: string
  status: string
  runs: { total: number; by_state: Record<string, number> }
}

/** Read a FastAPI `detail` whatever shape it arrives in.
 *
 *  It was previously used only when it was a string, so anything structured was
 *  discarded and the user saw "422 Unprocessable Entity" while the actual
 *  reason — which model, and the provider's own words — sat unread in the
 *  response body. FastAPI itself returns a LIST for validation errors, so this
 *  hid those too. */
export function describeDetail(detail: unknown): string | null {
  if (!detail) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // Validation errors: [{loc, msg, type}, ...]
    const parts = detail
      .map((d) =>
        typeof d === 'string'
          ? d
          : [(d as { loc?: unknown[] })?.loc?.join('.'), (d as { msg?: string })?.msg]
              .filter(Boolean)
              .join(': '),
      )
      .filter(Boolean)
    return parts.length ? parts.join('; ') : null
  }
  if (typeof detail === 'object') {
    const obj = detail as { message?: string; unusable?: { combination?: string; reason?: string }[] }
    const head = obj.message ?? ''
    const items = (obj.unusable ?? [])
      .map((u) => [u.combination, u.reason].filter(Boolean).join(' — '))
      .filter(Boolean)
    const joined = [head, ...items].filter(Boolean).join(': ')
    return joined || JSON.stringify(detail)
  }
  return String(detail)
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    // Surface the backend's own message — "repository uses git submodules" is
    // far more actionable than "422".
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      const explained = describeDetail(body?.detail)
      if (explained) detail = explained
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return (res.status === 204 ? null : await res.json()) as T
}

const get = <T,>(path: string) => req<T>(path)
const post = <T,>(path: string, body?: unknown) =>
  req<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
const put = <T,>(path: string, body: unknown) =>
  req<T>(path, { method: 'PUT', body: JSON.stringify(body) })

export const api = {
  health: () => get<{ status: string }>('/health'),
  experiments: () => get<Experiment[]>('/experiments'),
  repositories: () => get<Repository[]>('/repositories'),
  experiment: (id: string) => get<ExperimentStatus>(`/experiments/${id}`),
  results: (id: string) => get<ExperimentResults>(`/experiments/${id}/results`),
  // A written comparison of how the combinations did. POST and not automatic:
  // it costs a model call and would read differently on every page load.
  summary: (id: string) =>
    post<{ summary: string; provenance: Provenance; caveats: string[] }>(
      `/experiments/${id}/summary`,
    ),

  harnesses: () => get<Harness[]>('/harnesses'),
  providers: () => get<ProviderInfo[]>('/providers'),
  models: (provider = 'openrouter', freeOnly = true) =>
    get<ModelInfo[]>(`/providers/${provider}/models?free_only=${freeOnly}`),
  connection: (provider = 'openrouter') =>
    get<{ ok: boolean; latency_ms: number }>(`/providers/${provider}/connection`),
  snapshotModel: (provider: string, modelId: string) =>
    post<{ snapshot_id: string }>(`/providers/${provider}/models/${modelId}/snapshot`),

  addRepository: (body: { name: string; source: string; path_or_url: string }) =>
    post<{ id: string }>('/repositories', body),
  // analyze() only confirms it ran; fetch analysis() for the detail.
  analyze: (id: string) => post<{ analysis_id: string; supported: boolean }>(
    `/repositories/${id}/analyze`,
  ),
  analysis: (id: string) => get<Analysis>(`/repositories/${id}/analysis`),
  updateCommands: (id: string, commands: Record<string, string | null>) =>
    put<{ ok: boolean }>(`/repositories/${id}/commands`, commands),
  baseline: (id: string) => post<BaselineOutcome>(`/repositories/${id}/baseline`),
  // Read the last baseline without re-running install + the test suite.
  latestBaseline: (id: string) => get<BaselineOutcome>(`/repositories/${id}/baseline`),
  // Sends a bounded, secret-free repo digest to the model provider. One
  // request per call — deliberate, never automatic.
  suggest: (id: string) => post<Suggestion>(`/repositories/${id}/suggest`),
  // Decides HOW the repo can be evaluated and proves it by running a baseline
  // in a container. Slower than suggest() because it actually executes, which
  // is the entire point: it answers "can this repo be scored at all" before a
  // matrix is queued instead of after.
  evaluationStrategy: (id: string) =>
    post<StrategyDecision>(`/repositories/${id}/evaluation-strategy`),
  // Repairs how the suite RUNS (deps, pytest config, broken test files) and
  // keeps the patch only if it measurably improves the baseline.
  prepareTests: (id: string) => post<PrepareTestsResult>(`/repositories/${id}/prepare-tests`),
  commits: (id: string) => get<Commit[]>(`/repositories/${id}/commits`),

  createTask: (body: { repository_id: string; title: string; prompt: string }) =>
    post<{ id: string }>('/tasks', body),
  taskFromCommit: (body: { repository_id: string; sha: string }) =>
    post<{ id: string; base_commit: string; hidden_test_candidates: number }>(
      '/tasks/from-commit',
      body,
    ),
  // Slow and deliberate: rewrites the prompt and, when the commit shipped no
  // tests, generates one and PROVES it discriminates. Minutes, not a tick.
  prepareTask: (taskId: string, sha: string) =>
    post<PrepareTaskResult>(`/tasks/${taskId}/prepare`, { sha }),
  // Comprehension tasks: no test suite, no patch to apply, graded by rubric.
  // Creates the tasks so they can be ticked like commits.
  proposeTasks: (repoId: string) =>
    post<{ provenance: Provenance; tasks: ProposedTask[] }>(
      `/repositories/${repoId}/propose-tasks`,
    ),
  hiddenTests: (taskId: string) => get<HiddenTest[]>(`/tasks/${taskId}/hidden-tests`),
  approveHiddenTest: (id: string, approved: boolean) =>
    put<{ ok: boolean }>(`/hidden-tests/${id}`, { approved }),

  preview: (body: {
    task_ids: string[]
    harnesses: string[]
    model_ids: string[]
    repetitions: number
  }) => post<MatrixPreview>('/experiments/preview', body),
  createExperiment: (body: unknown) => post<{ id: string; runs: number }>('/experiments', body),

  progress: (id: string) => get<Progress>(`/experiments/${id}/progress`),
  pause: (id: string) => post<{ ok: boolean }>(`/experiments/${id}/pause`),
  resume: (id: string) => post<{ ok: boolean }>(`/experiments/${id}/resume`),
  cancelExperiment: (id: string) => post<{ ok: boolean }>(`/experiments/${id}/cancel`),
  cancelRun: (id: string) => post<{ ok: boolean }>(`/runs/${id}/cancel`),
  retryRun: (id: string) => post<{ ok: boolean }>(`/runs/${id}/retry`),

  runDetail: (id: string) => get<RunDetail>(`/runs/${id}/detail`),
  runPatch: (id: string) => get<{ patch: string; checksum: string }>(`/runs/${id}/patch`),
}

export const eventsUrl = (experimentId: string) => `${BASE}/experiments/${experimentId}/events`
