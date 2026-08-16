import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Live from './Live'
import { renderScreen } from '../test/render'
import { http, HttpResponse, server } from '../test/server'

// jsdom has no EventSource, and Live opens one. Stub it so the component falls
// back to polling — which is the path this test is exercising anyway.
class FakeEventSource {
  close() {}
  addEventListener() {}
  removeEventListener() {}
  onerror: unknown = null
  onmessage: unknown = null
}
vi.stubGlobal('EventSource', FakeEventSource)

const RUN = {
  run_id: 'run-abc123',
  harness: 'mini-swe-agent',
  model_id: 'openai/gpt-oss-20b:free',
  repetition: 1,
  state: 'RUNNING',
  error_category: null,
  elapsed_s: 42,
  model_requests: 3,
  input_tokens: 1000,
  output_tokens: 200,
  score: null,
  rate_limited: false,
  budget_exhausted: false,
}

const DETAIL = {
  id: 'run-abc123',
  harness: 'mini-swe-agent',
  model_id: 'openai/gpt-oss-20b:free',
  repetition: 1,
  state: 'RUNNING',
  error_category: null,
  error_message: null,
  has_patch: false,
  task: { title: 'Fix median()' },
  usage: { requests: 3, input_tokens: 1000, output_tokens: 200, cost_usd: 0 },
  evaluation: null,
  timeline: [],
  model_requests: [],
}

function mockExperiment(runs = [RUN], finished = false) {
  server.use(
    http.get('/api/v1/experiments/:id', () => HttpResponse.json({ id: 'e1', name: '1×1 smoke' })),
    http.get('/api/v1/experiments/:id/progress', () =>
      HttpResponse.json({ done: finished ? 1 : 0, total: 1, finished, runs }),
    ),
    http.get('/api/v1/runs/:id/detail', () => HttpResponse.json(DETAIL)),
  )
}

describe('Live', () => {
  it('shows the matrix rather than making you open each run', async () => {
    mockExperiment()
    renderScreen(<Live />, '/experiments/e1', '/experiments/:id')
    expect(await screen.findByText('1×1 smoke')).toBeInTheDocument()
    expect(await screen.findByText('mini-swe-agent')).toBeInTheDocument()
  })

  it('opens a run in place instead of navigating away from the matrix', async () => {
    mockExperiment()
    const user = userEvent.setup()
    renderScreen(<Live />, '/experiments/e1', '/experiments/:id')

    await user.click(await screen.findByRole('button', { name: 'inspect' }))

    // The run's own detail appears…
    expect(await screen.findByText('Fix median()')).toBeInTheDocument()
    // …and the matrix is still on screen, which is the point of merging them.
    expect(screen.getByText('Runs')).toBeInTheDocument()
  })

  it('offers to cancel a running run — the UI could previously only start work', async () => {
    mockExperiment()
    const user = userEvent.setup()
    renderScreen(<Live />, '/experiments/e1', '/experiments/:id')

    await user.click(await screen.findByRole('button', { name: 'inspect' }))
    expect(await screen.findByRole('button', { name: /Cancel run/ })).toBeInTheDocument()
  })

  it('does not offer to cancel a run that already finished', async () => {
    server.use(
      http.get('/api/v1/experiments/:id', () => HttpResponse.json({ id: 'e1', name: 'done' })),
      http.get('/api/v1/experiments/:id/progress', () =>
        HttpResponse.json({
          done: 1,
          total: 1,
          finished: true,
          runs: [{ ...RUN, state: 'COMPLETED', score: 0.5 }],
        }),
      ),
      http.get('/api/v1/runs/:id/detail', () =>
        HttpResponse.json({ ...DETAIL, state: 'COMPLETED' }),
      ),
    )
    const user = userEvent.setup()
    renderScreen(<Live />, '/experiments/e1', '/experiments/:id')

    await user.click(await screen.findByRole('button', { name: 'inspect' }))
    expect(await screen.findByText('Fix median()')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cancel run/ })).not.toBeInTheDocument()
  })

  it('says a run produced no patch rather than showing an empty box', async () => {
    mockExperiment()
    const user = userEvent.setup()
    renderScreen(<Live />, '/experiments/e1', '/experiments/:id')

    await user.click(await screen.findByRole('button', { name: 'inspect' }))
    expect(await screen.findByText(/No patch produced/)).toBeInTheDocument()
  })
})
