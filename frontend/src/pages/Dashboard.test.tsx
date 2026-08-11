import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import Dashboard from './Dashboard'
import { http, HttpResponse, server } from '../test/server'

function renderWithQuery(ui: ReactElement) {
  // retry:false so error states assert immediately instead of after backoff.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('Dashboard', () => {
  it('shows empty states when the backend has no data', async () => {
    renderWithQuery(<Dashboard />)
    expect(await screen.findByText('No repositories yet.')).toBeInTheDocument()
    expect(await screen.findByText('No experiments yet.')).toBeInTheDocument()
  })

  it('reports the backend as ok when health succeeds', async () => {
    renderWithQuery(<Dashboard />)
    expect(await screen.findByText('backend: ok')).toBeInTheDocument()
  })

  it('warns instead of silently looking healthy when the backend is down', async () => {
    server.use(http.get('/api/v1/health', () => HttpResponse.error()))
    renderWithQuery(<Dashboard />)
    // The health query sets retry:1 of its own, so the error state only
    // settles after that retry — allow for it rather than racing the default
    // 1s timeout. The chip alone is a weak assertion (it reads "offline"
    // while merely loading); the alert is what proves isError was reached.
    expect(await screen.findByText(/Backend unreachable/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('backend: offline')).toBeInTheDocument()
  })

  it('lists repositories and experiments returned by the api', async () => {
    server.use(
      http.get('/api/v1/repositories', () =>
        HttpResponse.json([
          { id: 'r1', name: 'python-bug-repo', source: 'local', path_or_url: '/tmp/x' },
        ]),
      ),
      http.get('/api/v1/experiments', () =>
        HttpResponse.json([{ id: 'e1', name: 'smoke', status: 'running' }]),
      ),
    )
    renderWithQuery(<Dashboard />)
    expect(await screen.findByText('python-bug-repo')).toBeInTheDocument()
    expect(await screen.findByText('smoke')).toBeInTheDocument()
    expect(await screen.findByText('running')).toBeInTheDocument()
  })
})
