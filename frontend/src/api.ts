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

export const api = {
  health: () => get<{ status: string }>('/health'),
  experiments: () => get<Experiment[]>('/experiments'),
  repositories: () => get<Repository[]>('/repositories'),
}
