import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import RunPanel from './RunPanel'
import { renderScreen } from '../test/render'
import { http, HttpResponse, server } from '../test/server'

const ANSWER = `# Battle Turn Trace

The battle turn flows through three files, in this order:
1. src/server.py — MCP tool entry point`

const detail = (over: Partial<Record<string, unknown>> = {}) => ({
  id: 'r1',
  state: 'COMPLETED',
  harness: 'smolagents',
  model_id: 'nvidia/nemotron-3-ultra-550b-a55b',
  repetition: 1,
  task: { id: 't1', title: 'Single battle turn flow', prompt: 'p', kind: 'theory' },
  error_category: null,
  error_message: null,
  started_at: null,
  completed_at: null,
  result: { final_message: ANSWER },
  usage: { requests: 2, input_tokens: 12217, output_tokens: 7037, cost_usd: 0 },
  evaluation: null,
  evaluations: [],
  model_requests: [],
  timeline: [],
  has_patch: false,
  ...over,
})

const verdict = (over: Partial<Record<string, unknown>> = {}) => ({
  task_id: 't1',
  task_title: 'Single battle turn flow',
  signal: 'ok',
  score: 0.5,
  results: {
    judge: { score: 0.5, met: ['entry point delegates'], partial: [], missing: [], invented: [] },
    answer_source: 'final_message',
    answer_chars: ANSWER.length,
  },
  ...over,
})

function serve(body: Record<string, unknown>) {
  server.use(http.get('/api/v1/runs/:id/detail', () => HttpResponse.json(body)))
}

const render = () => renderScreen(<RunPanel runId="r1" />)

describe('RunPanel output', () => {
  it('renders the written answer for a run that produced no patch', async () => {
    // The whole deliverable of a comprehension run. It was previously reachable
    // only by opening the database, while the tab said "No patch produced".
    serve(detail())
    render()

    expect(await screen.findByText(/Battle Turn Trace/)).toBeInTheDocument()
    expect(screen.getByText(/from final_message/)).toBeInTheDocument()
    expect(screen.queryByText(/No patch and no answer/)).not.toBeInTheDocument()
  })

  it('still renders a diff for a run that produced a patch', async () => {
    serve(detail({ has_patch: true, result: {} }))
    server.use(
      http.get('/api/v1/runs/:id/patch', () =>
        HttpResponse.json({ run_id: 'r1', checksum: 'x', patch: '--- a/x\n+++ b/x\n+added line' }),
      ),
    )
    render()

    expect(await screen.findByText(/\+added line/)).toBeInTheDocument()
  })

  it('says so plainly when there is neither', async () => {
    serve(detail({ result: {} }))
    render()

    expect(await screen.findByText(/No patch and no answer/)).toBeInTheDocument()
  })
})

describe('RunPanel evaluation', () => {
  it('shows one verdict per task for a grouped run', async () => {
    // A grouped run answers several questions from one exploration. Showing a
    // single grade left you unable to tell which question it belonged to.
    serve(
      detail({
        evaluations: [
          verdict(),
          verdict({ task_id: 't2', task_title: 'Add a battle turn limit', score: 0.25 }),
        ],
      }),
    )
    render()
    await userEvent.click(await screen.findByRole('tab', { name: 'Evaluation' }))

    // Twice: the run header names the first task, and so does its own verdict.
    expect(screen.getAllByText('Single battle turn flow')).toHaveLength(2)
    // The second task appears nowhere but its verdict — before this it was
    // simply absent from the screen.
    expect(screen.getByText('Add a battle turn limit')).toBeInTheDocument()
    expect(screen.getByText(/answered 2 tasks from one exploration/)).toBeInTheDocument()
  })

  it('does not repeat the task title when there is only one', async () => {
    serve(detail({ evaluations: [verdict()] }))
    render()
    await userEvent.click(await screen.findByRole('tab', { name: 'Evaluation' }))

    // Once in the run header, not again above its own verdict.
    expect(screen.getAllByText('Single battle turn flow')).toHaveLength(1)
    // Present in the rubric; also in the raw dump below it, hence getAll.
    expect(screen.getAllByText(/entry point delegates/).length).toBeGreaterThan(0)
  })
})

describe('RunPanel model calls', () => {
  it('shows why a request failed and explains that rows are attempts', async () => {
    // A 503 used to render as a bare number: the reason was already in the
    // payload and simply never displayed.
    serve(
      detail({
        usage: { requests: 3, failed_requests: 2, input_tokens: 10, output_tokens: 5 },
        model_requests: [
          {
            http_status: 503,
            latency_ms: 700,
            input_tokens: null,
            output_tokens: null,
            routed_provider: null,
            error: 'provider error (503): Service Unavailable',
          },
          {
            http_status: 200,
            latency_ms: 7179,
            input_tokens: 10,
            output_tokens: 5,
            routed_provider: 'nvidia',
            error: null,
          },
        ],
      }),
    )
    render()
    await userEvent.click(await screen.findByRole('tab', { name: 'Model calls' }))

    expect(screen.getByText(/Service Unavailable/)).toBeInTheDocument()
    expect(screen.getByText(/Each row is one attempt/)).toBeInTheDocument()
  })

  it('labels the request count as attempts once a retry has happened', async () => {
    serve(detail({ usage: { requests: 3, failed_requests: 2 } }))
    render()

    expect(await screen.findByText(/attempts, incl\. retries/)).toBeInTheDocument()
    expect(screen.getByText(/2 failed/)).toBeInTheDocument()
  })
})
