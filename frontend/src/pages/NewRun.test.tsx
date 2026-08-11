import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import NewRun from './NewRun'
import { renderScreen } from '../test/render'
import { http, HttpResponse, server } from '../test/server'

/** Drive the wizard to the Matrix step so the quota maths can be asserted. */
async function reachMatrixStep() {
  server.use(
    http.post('/api/v1/repositories', () => HttpResponse.json({ id: 'r1' })),
    http.post('/api/v1/repositories/:id/analyze', () =>
      HttpResponse.json({ analysis_id: 'a1', supported: true }),
    ),
    http.get('/api/v1/repositories/:id/analysis', () =>
      HttpResponse.json({
        languages: ['python'],
        package_managers: ['pip'],
        dependency_files: [],
        test_locations: ['tests/'],
        ci_workflows: [],
        runtime_versions: {},
        supported: true,
        size_bytes: 1_200_000,
        commands: { install: null, build: null, test: 'pytest -q', test_framework: 'pytest' },
      }),
    ),
    http.put('/api/v1/repositories/:id/commands', () => HttpResponse.json({ ok: true })),
    http.post('/api/v1/repositories/:id/baseline', () =>
      HttpResponse.json({
        baseline_id: 'b1',
        benchmarkable: true,
        warn: false,
        steps: { test: { exit_code: 0 } },
      }),
    ),
    http.post('/api/v1/tasks', () => HttpResponse.json({ id: 'task1' })),
  )

  const user = userEvent.setup()
  renderScreen(<NewRun />)

  await user.type(screen.getByPlaceholderText(/Projects\/your-repo/), '/tmp/repo')
  await user.click(screen.getByRole('button', { name: /Analyze repository/ }))

  await user.click(await screen.findByRole('button', { name: /Save and continue/ }))
  await user.click(await screen.findByRole('button', { name: /Run baseline/ }))
  await user.click(await screen.findByRole('button', { name: /^Continue$/ }))

  await user.type(await screen.findByLabelText('title'), 'Fix median')
  await user.type(screen.getByLabelText('prompt'), 'median() is wrong for even lists')
  await user.click(screen.getByRole('button', { name: /Add task/ }))
  await user.click(await screen.findByRole('button', { name: /^Continue$/ }))

  return user
}

describe('NewRun wizard', () => {
  it('will not start a run with nothing selected', async () => {
    const user = await reachMatrixStep()
    const start = await screen.findByRole('button', { name: /Start 0 runs/ })
    expect(start).toBeDisabled()
    // Nothing chosen yet, so no request budget is implied either.
    expect(await screen.findByText('total runs')).toBeInTheDocument()
    void user
  })

  it('computes the expanded matrix from the selections', async () => {
    const user = await reachMatrixStep()
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(screen.getByLabelText(/smolagents/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))

    // 2 harnesses x 1 model x 1 task x 1 rep
    expect(await screen.findByRole('button', { name: /Start 2 runs/ })).toBeEnabled()
  })

  it('warns when the matrix needs more requests than a free-tier day', async () => {
    const user = await reachMatrixStep()
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))

    const reps = screen.getByLabelText('repetitions')
    await user.clear(reps)
    await user.type(reps, '9')

    // 1 x 1 x 1 x 9 runs x 8 requests = 72 > ~50/day
    await waitFor(async () =>
      expect(await screen.findByText(/more than a free-tier day/)).toBeInTheDocument(),
    )
  })

  it('flags that fewer than three repetitions cannot support a reliability claim', async () => {
    const user = await reachMatrixStep()
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))
    expect(await screen.findByText(/statistically weak/)).toBeInTheDocument()
    void user
  })
})
