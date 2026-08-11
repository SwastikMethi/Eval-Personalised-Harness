import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Dashboard from './Dashboard'
import { renderScreen } from '../test/render'
import { http, HttpResponse, server } from '../test/server'

describe('Dashboard', () => {
  it('tells you what to do when there is nothing yet', async () => {
    renderScreen(<Dashboard />)
    expect(await screen.findByText(/No experiments yet/)).toBeInTheDocument()
    expect(await screen.findByText('No repositories registered.')).toBeInTheDocument()
  })

  it('warns instead of silently looking healthy when the backend is down', async () => {
    server.use(http.get('/api/v1/health', () => HttpResponse.error()))
    renderScreen(<Dashboard />)
    expect(
      await screen.findByText(/Backend unreachable/, {}, { timeout: 5000 }),
    ).toBeInTheDocument()
  })

  it('lists experiments and repositories with their status', async () => {
    server.use(
      http.get('/api/v1/experiments', () =>
        HttpResponse.json([{ id: 'e1', name: '2×3 smoke', status: 'running' }]),
      ),
      http.get('/api/v1/repositories', () =>
        HttpResponse.json([
          { id: 'r1', name: 'python-bug-repo', source: 'local', path_or_url: '/tmp/x' },
        ]),
      ),
    )
    renderScreen(<Dashboard />)
    expect(await screen.findByText('2×3 smoke')).toBeInTheDocument()
    expect(await screen.findByText('running')).toBeInTheDocument()
    expect(await screen.findByText('python-bug-repo')).toBeInTheDocument()
  })

  it('links each experiment to its detail page', async () => {
    server.use(
      http.get('/api/v1/experiments', () =>
        HttpResponse.json([{ id: 'abc123', name: 'run', status: 'completed' }]),
      ),
    )
    renderScreen(<Dashboard />)
    const link = (await screen.findByText('run')).closest('a')
    expect(link).toHaveAttribute('href', '/experiments/abc123')
  })
})
