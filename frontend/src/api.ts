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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
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

export const api = {
  health: () => get<{ status: string }>('/health'),
  experiments: () => get<Experiment[]>('/experiments'),
  repositories: () => get<Repository[]>('/repositories'),
  experiment: (id: string) => get<ExperimentStatus>(`/experiments/${id}`),
  results: (id: string) => get<ExperimentResults>(`/experiments/${id}/results`),
}
