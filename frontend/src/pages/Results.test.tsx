import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Results from './Results'
import { renderScreen } from '../test/render'
import { http, HttpResponse, server } from '../test/server'

const combo = (over: Partial<Record<string, unknown>> = {}) => ({
  combination_id: 'c1',
  harness: 'mini-swe-agent',
  model_id: 'openai/gpt-oss-20b:free',
  task_id: 't1',
  runs: 3,
  completed: 3,
  success_rate: 1,
  mean_score: 0.9,
  stdev_score: 0.05,
  timeout_rate: 0,
  empty_patch_rate: 0,
  crash_rate: 0,
  mean_duration_s: 120,
  mean_tokens: 8000,
  eligible: true,
  ineligible_reasons: [],
  statistically_weak: false,
  weighted_score: 0.82,
  ...over,
})

const payload = (over: Partial<Record<string, unknown>> = {}) => ({
  combinations: [combo()],
  recommendations: {
    best_balanced: {
      harness: 'mini-swe-agent',
      model_id: 'openai/gpt-oss-20b:free',
      tasks: 1,
      completed_reps: 3,
      correctness: 0.9,
      reliability: 1,
      efficiency: 0.7,
      balanced: 0.82,
      avg_duration_s: 120,
      avg_tokens: 8000,
      failure_rate: 0,
      statistically_weak: false,
      why: 'highest weighted score',
    },
  },
  pareto: { correctness_vs_tokens: ['c1'], correctness_vs_duration: [] },
  caveats: ['efficiency scores are cohort-relative within each task'],
  ...over,
})

const serve = (body: Record<string, unknown>) =>
  server.use(http.get('/api/v1/experiments/:id/results', () => HttpResponse.json(body)))

describe('Results', () => {
  it('says results are pending rather than showing an empty table', async () => {
    serve({ combinations: [], recommendations: {}, pareto: {} })
    renderScreen(<Results experimentId="e1" />)
    expect(await screen.findByText(/No results yet/)).toBeInTheDocument()
  })

  it('shows the winning combination and why it won', async () => {
    serve(payload())
    renderScreen(<Results experimentId="e1" />)
    expect(await screen.findByText('Best balanced')).toBeInTheDocument()
    expect(await screen.findByText('highest weighted score')).toBeInTheDocument()
  })

  it('names a card as having no winner rather than inventing one', async () => {
    serve(payload({ recommendations: {} }))
    renderScreen(<Results experimentId="e1" />)
    // All four cards must still render, each stating there is no winner.
    expect(await screen.findByText('Best quality')).toBeInTheDocument()
    expect((await screen.findAllByText('No eligible combination.')).length).toBe(4)
  })

  it('flags a statistically weak recommendation', async () => {
    const body = payload()
    ;(body.recommendations as any).best_balanced.statistically_weak = true
    serve(body)
    renderScreen(<Results experimentId="e1" />)
    expect(await screen.findByText('statistically weak')).toBeInTheDocument()
  })

  it('marks excluded combinations and explains why', async () => {
    serve(
      payload({
        combinations: [
          combo({
            eligible: false,
            ineligible_reasons: ['never produces a patch', 'no completed repetitions'],
            weighted_score: null,
            mean_score: null,
          }),
        ],
      }),
    )
    renderScreen(<Results experimentId="e1" />)
    expect(await screen.findByText('excluded')).toBeInTheDocument()
    expect(await screen.findByText('never produces a patch')).toBeInTheDocument()
  })

  it('always surfaces the caveats — the numbers must not look more solid than they are', async () => {
    serve(payload())
    renderScreen(<Results experimentId="e1" />)
    expect(await screen.findByText(/cohort-relative/)).toBeInTheDocument()
  })
})
