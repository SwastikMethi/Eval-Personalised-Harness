import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import Wizard from './Wizard'
import { renderScreen } from '../test/render'
import { http, HttpResponse, server } from '../test/server'

const ANALYSIS = {
  languages: ['python'],
  package_managers: ['pip'],
  dependency_files: [],
  test_locations: ['tests/'],
  ci_workflows: [],
  runtime_versions: {},
  supported: true,
  size_bytes: 1_200_000,
  // Only `test` is detected — build/lint/typecheck legitimately absent.
  commands: { install: null, build: null, test: 'pytest -q', test_framework: 'pytest' },
}

const BASELINE = {
  baseline_id: 'b1',
  base_commit: 'abc123',
  benchmarkable: true,
  warn: false,
  steps: { test: { exit_code: 0 } },
  test_case_count: 12,
}

const COMMITS = [
  {
    sha: 'aaaaaaaa1111',
    subject: 'Fix median() for even-length lists',
    author: 'you',
    date: '2026-08-01T10:00:00Z',
    parent: 'parent1',
  },
  {
    sha: 'bbbbbbbb2222',
    subject: 'Add input validation',
    author: 'you',
    date: '2026-07-30T10:00:00Z',
    parent: 'parent2',
  },
]

function mockRepo(over: { analysis?: unknown; baseline?: unknown } = {}) {
  server.use(
    http.post('/api/v1/repositories', () => HttpResponse.json({ id: 'r1' })),
    http.post('/api/v1/repositories/:id/analyze', () =>
      HttpResponse.json({ analysis_id: 'a1', supported: true }),
    ),
    http.get('/api/v1/repositories/:id/analysis', () =>
      HttpResponse.json((over.analysis ?? ANALYSIS) as never),
    ),
    http.post('/api/v1/repositories/:id/baseline', () =>
      HttpResponse.json((over.baseline ?? BASELINE) as never),
    ),
    http.put('/api/v1/repositories/:id/commands', () => HttpResponse.json({ ok: true })),
    http.get('/api/v1/repositories/:id/commits', () => HttpResponse.json(COMMITS)),
    http.post('/api/v1/tasks/from-commit', () =>
      HttpResponse.json({ id: 'task1', base_commit: 'parent1', hidden_test_candidates: 0 }),
    ),
  )
}

/**
 * Repo → tick a commit → land on the Agent stacks step.
 *
 * The wizard used to put harnesses, models, the matrix and launch on one step.
 * They are now two ("which stacks compete" and "what exactly will happen"), so
 * tests about stacks stop here and tests about the matrix continue with
 * reachReview(). The assertions themselves are unchanged.
 */
async function reachCombos() {
  const user = userEvent.setup()
  renderScreen(<Wizard />)
  await user.type(screen.getByPlaceholderText(/Projects\/your-repo/), '/tmp/repo')
  await user.click(screen.getByRole('button', { name: /Analyze repository/ }))
  await user.click(await screen.findByLabelText(/Fix median/))
  await user.click(await screen.findByRole('button', { name: /^Continue$/ }))
  return user
}

/**
 * Open the stack picker. Harnesses and models used to be two lists sitting on
 * the page; they are now a dialog behind the "add a stack" card, because the
 * screen's subject is the pairing, not the two ingredient lists.
 */
async function openPicker(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /Choose harnesses and models|Add agent stack/ }))
}

/** …and on through Agent stacks to Review, where the matrix and launch live. */
async function reachReview() {
  const user = await reachCombos()
  await openPicker(user)
  await user.click(await screen.findByLabelText(/mini-swe-agent/))
  await user.click(await screen.findByLabelText(/gpt-oss-20b/))
  await user.click(screen.getByRole('button', { name: /^Add \d+ stacks?$/ }))
  await user.click(await screen.findByRole('button', { name: /^Continue$/ }))
  return user
}

const PROPOSED = {
  provenance: { provider: 'openai', model: 'gpt-5.6-sol' },
  tasks: [
    {
      id: 'theory1',
      title: 'Explain the run lifecycle',
      category: 'execution_flow',
      rubric: [{ criterion: 'names the queue worker', evidence: 'queue.py', depth: 'structural' }],
      dropped: [],
    },
  ],
}

/**
 * Repo → propose comprehension questions → tick one → Review.
 *
 * Deliberately never touches a commit, because that is the whole condition:
 * a rubric-graded matrix needs no test suite and no baseline.
 */
async function reachReviewViaTheory() {
  // The commit shortlist fires automatically on reaching Tasks; without a
  // handler MSW retries it and the flow stalls.
  server.use(
    http.post('/api/v1/repositories/:id/suggest', () =>
      HttpResponse.json({
        model_id: 'gpt-5.6-sol',
        confidence: 'high',
        commands: {},
        rationale: {},
        commits: [],
        files_read: [],
      }),
    ),
  )
  const user = userEvent.setup()
  renderScreen(<Wizard />)
  await user.type(screen.getByPlaceholderText(/Projects\/your-repo/), '/tmp/repo')
  await user.click(screen.getByRole('button', { name: /Analyze repository/ }))

  await user.click(await screen.findByRole('button', { name: /Understand the code/ }))
  await user.click(await screen.findByRole('button', { name: /Propose questions/ }))
  await user.click(await screen.findByLabelText(/Explain the run lifecycle/))
  await user.click(await screen.findByRole('button', { name: /^Continue$/ }))

  await openPicker(user)
  await user.click(await screen.findByLabelText(/mini-swe-agent/))
  await user.click(await screen.findByLabelText(/gpt-oss-20b/))
  await user.click(screen.getByRole('button', { name: /^Add \d+ stacks?$/ }))
  await user.click(await screen.findByRole('button', { name: /^Continue$/ }))
  return user
}

describe('Agent stacks are chosen pairs, not a grid', () => {
  it('adds one stack for one harness and one model', async () => {
    mockRepo()
    const user = await reachCombos()
    await openPicker(user)
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))
    await user.click(screen.getByRole('button', { name: /^Add 1 stack$/ }))

    expect(await screen.findByText('1 agent stack')).toBeInTheDocument()
  })

  it('accumulates across visits instead of replacing', async () => {
    // The property the whole change exists for: two hand-picked pairs, not the
    // four that crossing both selections would have produced.
    mockRepo()
    const user = await reachCombos()

    await openPicker(user)
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))
    await user.click(screen.getByRole('button', { name: /^Add 1 stack$/ }))

    await openPicker(user)
    await user.click(await screen.findByLabelText(/smolagents/))
    await user.click(await screen.findByLabelText(/north-mini-code/))
    await user.click(screen.getByRole('button', { name: /^Add 1 stack$/ }))

    expect(await screen.findByText('2 agent stacks')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /^Continue$/ }))
    expect(await screen.findByRole('button', { name: /Start 2 runs/ })).toBeEnabled()
  })

  it('can mix providers in one matrix', async () => {
    mockRepo()
    const { NIM_MODELS, OPENROUTER_MODELS } = await import('../test/server')
    server.use(
      http.get('/api/v1/providers/:provider/models', ({ params }) =>
        HttpResponse.json(params.provider === 'nvidia' ? NIM_MODELS : OPENROUTER_MODELS),
      ),
    )
    const user = await reachCombos()

    await openPicker(user)
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))
    await user.click(screen.getByRole('button', { name: /^Add 1 stack$/ }))

    await openPicker(user)
    await user.click(await screen.findByRole('button', { name: /nvidia/ }))
    await user.click(await screen.findByLabelText(/smolagents/))
    await user.click(await screen.findByLabelText(/deepseek-coder/))
    await user.click(screen.getByRole('button', { name: /^Add 1 stack$/ }))

    expect(await screen.findByText('2 agent stacks')).toBeInTheDocument()
    // Both providers named on the cards — the provider is part of a stack's
    // identity now, so it has to be visible.
    expect(await screen.findByText('openrouter')).toBeInTheDocument()
    expect(await screen.findByText('nvidia')).toBeInTheDocument()
  })

  it('removes a single stack without re-multiplying the rest', async () => {
    mockRepo()
    const user = await reachCombos()
    await openPicker(user)
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(await screen.findByLabelText(/smolagents/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))
    await user.click(screen.getByRole('button', { name: /^Add 2 stacks$/ }))

    expect(await screen.findByText('2 agent stacks')).toBeInTheDocument()
    await user.click((await screen.findAllByRole('button', { name: /^remove$/ }))[0])
    expect(await screen.findByText('1 agent stack')).toBeInTheDocument()
  })

  it('does not add the same stack twice', async () => {
    mockRepo()
    const user = await reachCombos()
    for (const _ of [1, 2]) {
      await openPicker(user)
      await user.click(await screen.findByLabelText(/mini-swe-agent/))
      await user.click(await screen.findByLabelText(/gpt-oss-20b/))
      await user.click(screen.getByRole('button', { name: /^Add 1 stack$/ }))
    }
    expect(await screen.findByText('1 agent stack')).toBeInTheDocument()
  })
})

describe('Comprehension-only matrix', () => {
  it('never runs a baseline, and never blocks on one', { timeout: 30_000 }, async () => {
    let baselineCalls = 0
    mockRepo({ analysis: { ...ANALYSIS, commands: { test: null, test_framework: null } } })
    server.use(
      http.post('/api/v1/repositories/:id/baseline', () => {
        baselineCalls += 1
        return HttpResponse.json(BASELINE)
      }),
      http.post('/api/v1/repositories/:id/propose-tasks', () => HttpResponse.json(PROPOSED)),
    )

    await reachReviewViaTheory()

    // Startable despite no test command and no baseline — the rubric is the signal.
    expect(await screen.findByRole('button', { name: /Start 1 run/ })).toBeEnabled()
    expect(screen.queryByText(/no correctness signal without one/)).not.toBeInTheDocument()
    // And the container work was never paid for.
    expect(baselineCalls).toBe(0)
  })

  it('says why setup is empty rather than looking unconfigured', { timeout: 30_000 }, async () => {
    mockRepo()
    server.use(
      http.post('/api/v1/repositories/:id/propose-tasks', () => HttpResponse.json(PROPOSED)),
    )
    await reachReviewViaTheory()
    expect(await screen.findByText(/no test suite, no patch/)).toBeInTheDocument()
  })
})

describe('Setup wizard', () => {
  it('reaches the combos step without ever asking for build or typecheck', async () => {
    mockRepo()
    await reachCombos()

    // The whole point: the user got here without meeting an optional field.
    expect(await screen.findByText('Choose the stacks')).toBeInTheDocument()
    expect(screen.queryByLabelText('build (optional)')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('typecheck (optional)')).not.toBeInTheDocument()
  })

  it('keeps setup collapsed when nothing needs attention', async () => {
    mockRepo()
    await reachReview()
    expect(await screen.findByText(/baseline passed/)).toBeInTheDocument()
    // Collapsed: the editable commands are not reachable until asked for.
    expect(screen.queryByLabelText('build (optional)')).not.toBeInTheDocument()
  })

  it('marks optional commands as optional once setup is opened', async () => {
    mockRepo()
    const user = await reachReview()
    await user.click(await screen.findByText('review'))
    for (const field of ['install', 'build', 'lint', 'typecheck']) {
      expect(await screen.findByLabelText(`${field} (optional)`)).toBeInTheDocument()
    }
    expect((await screen.findAllByText('leave blank to skip')).length).toBe(4)
  })

  it('auto-expands setup and blocks starting when there is no test command', async () => {
    mockRepo({
      analysis: { ...ANALYSIS, commands: { test: null, test_framework: null } },
    })
    await reachReview()

    // Opened itself — the user did not have to go looking.
    expect(await screen.findByLabelText('build (optional)')).toBeInTheDocument()
    expect(await screen.findByText(/no correctness signal without one/)).toBeInTheDocument()
  })

  it('blocks starting when the baseline could not establish a signal', async () => {
    mockRepo({ baseline: { ...BASELINE, benchmarkable: false } })
    await reachReview()
    expect(await screen.findByText(/baseline could not establish a signal/)).toBeInTheDocument()
  })

  it('states the reason rather than showing a dead button', async () => {
    mockRepo()
    await reachCombos()
    // Same intent as before, now enforced one step earlier: Review is only
    // reachable once a stack exists, so the empty-selection case is stated here.
    const cont = await screen.findByRole('button', { name: /^Continue$/ })
    expect(cont).toBeDisabled()
    expect(
      await screen.findByText('pick at least one harness and one model'),
    ).toBeInTheDocument()
  })

  it('computes the expanded matrix from the selections', async () => {
    mockRepo()
    const user = await reachCombos()
    await openPicker(user)
    await user.click(await screen.findByLabelText(/mini-swe-agent/))
    await user.click(screen.getByLabelText(/smolagents/))
    await user.click(await screen.findByLabelText(/gpt-oss-20b/))
    await user.click(screen.getByRole('button', { name: /^Add \d+ stacks?$/ }))
    await user.click(await screen.findByRole('button', { name: /^Continue$/ }))

    // 2 harnesses × 1 model × 1 task × 1 rep
    expect(await screen.findByRole('button', { name: /Start 2 runs/ })).toBeEnabled()
  })

  it('warns when the matrix needs more requests than a free-tier day', async () => {
    mockRepo()
    const user = await reachReview()

    const reps = screen.getByLabelText('repetitions')
    await user.clear(reps)
    await user.type(reps, '9')

    // 1 × 1 × 1 × 9 runs × 8 requests = 72 > ~50/day
    await waitFor(async () =>
      expect(await screen.findByText(/more than a free-tier day/)).toBeInTheDocument(),
    )
  })

  it('surfaces a clone failure instead of claiming there are no commits', async () => {
    // A failed GitHub clone used to render identically to "no commits found",
    // which is what made a perfectly good repo look empty.
    server.use(
      http.post('/api/v1/repositories', () => HttpResponse.json({ id: 'r1' })),
      http.post('/api/v1/repositories/:id/analyze', () =>
        HttpResponse.json({ analysis_id: 'a1', supported: true }),
      ),
      http.get('/api/v1/repositories/:id/analysis', () => HttpResponse.json(ANALYSIS)),
      http.post('/api/v1/repositories/:id/baseline', () => HttpResponse.json(BASELINE)),
      http.get('/api/v1/repositories/:id/commits', () =>
        HttpResponse.json({ detail: 'clone failed: repository not found' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderScreen(<Wizard />)
    await user.type(screen.getByPlaceholderText(/Projects\/your-repo/), '/tmp/repo')
    await user.click(screen.getByRole('button', { name: /Analyze repository/ }))

    expect(await screen.findByText(/Could not read commits/)).toBeInTheDocument()
    expect(screen.queryByText(/No commits with a parent found/)).not.toBeInTheDocument()
  })

  it('fills commands from an AI suggestion without saving them', async () => {
    mockRepo()
    server.use(
      http.post('/api/v1/repositories/:id/suggest', () =>
        HttpResponse.json({
          model_id: 'cohere/north-mini-code:free',
          confidence: 'high',
          commands: {
            install: 'pip install -e .',
            build: null,
            test: 'pytest -q',
            lint: 'ruff check .',
            typecheck: null,
            test_framework: 'pytest',
          },
          rationale: { test: 'pyproject.toml configures pytest' },
          commits: [{ sha: 'aaaaaaaa1111', why: 'fixes a bug and adds a test', subject: 'Fix median', parent: 'p1' }],
          files_read: ['pyproject.toml', 'README.md'],
        }),
      ),
    )
    const user = await reachReview()
    await user.click(await screen.findByText('review'))
    await user.click(screen.getByRole('button', { name: /Suggest with AI/ }))

    expect(await screen.findByDisplayValue('pip install -e .')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('ruff check .')).toBeInTheDocument()
    // Provenance shown, and the rationale replaces the generic helper text.
    expect(await screen.findByText(/AI: pyproject.toml configures pytest/)).toBeInTheDocument()
    // Suggestions are unverified until the baseline re-runs against them.
    expect(await screen.findByText(/Commands changed since this baseline ran/)).toBeInTheDocument()
  })

  it('discloses what the AI button transmits before it is pressed', async () => {
    mockRepo()
    const user = await reachReview()
    await user.click(await screen.findByText('review'))
    // Matched on the substance rather than the sentence, so rewording the
    // copy does not fail a test whose point is that disclosure exists.
    expect(await screen.findByText(/file names, README, manifests/)).toBeInTheDocument()
    expect(await screen.findByText(/secrets \(.env, keys\) are never included/)).toBeInTheDocument()
  })

  it('shows the verified strategy, its evidence, and who decided it', async () => {
    mockRepo()
    server.use(
      http.post('/api/v1/repositories/:id/evaluation-strategy', () =>
        HttpResponse.json({
          strategy: 'repo_tests',
          scoreable: true,
          meaning: "Graded against the repository's own suite",
          warn: false,
          commands: { install: 'pip install -r requirements.txt', test: 'pytest -v' },
          provenance: { provider: 'anthropic', model: 'claude-opus-5' },
          rationale: {},
          attempts: [
            { rung: 1, strategy: 'commit_tests', ok: false, reason: 'no commit adds tests', evidence: {} },
            { rung: 2, strategy: 'repo_tests', ok: true, reason: '5 test case(s) parsed', evidence: {} },
          ],
          commits: [],
        }),
      ),
    )
    const user = await reachReview()
    await user.click(await screen.findByText('review'))
    await user.click(await screen.findByRole('button', { name: /Analyse & verify/i }))

    // Appears as both the headline verdict and the passing ladder rung.
    expect((await screen.findAllByText(/repo tests/)).length).toBeGreaterThan(0)
    // The ladder is shown so a verdict can be argued with, not just accepted.
    expect(await screen.findByText(/5 test case\(s\) parsed/)).toBeInTheDocument()
    expect(await screen.findByText(/claude-opus-5/)).toBeInTheDocument()
  })

  it('says plainly when a repo cannot be scored, before any run is queued', async () => {
    mockRepo()
    server.use(
      http.post('/api/v1/repositories/:id/evaluation-strategy', () =>
        HttpResponse.json({
          strategy: 'unbenchmarkable',
          scoreable: false,
          meaning: 'No runnable check was found, so patches cannot be verified.',
          warn: false,
          commands: { install: 'pip install -r requirements.txt' },
          provenance: { provider: 'anthropic', model: 'claude-opus-5' },
          rationale: {},
          attempts: [
            { rung: 3, strategy: 'build_only', ok: false, reason: 'no build command', evidence: {} },
          ],
          commits: [],
        }),
      ),
    )
    const user = await reachReview()
    await user.click(await screen.findByText('review'))
    await user.click(await screen.findByRole('button', { name: /Analyse & verify/i }))

    expect(await screen.findByText(/cannot be scored/)).toBeInTheDocument()
  })

  it('offers each configured provider and swaps the model list', async () => {
    mockRepo()
    const { NIM_MODELS } = await import('../test/server')
    server.use(
      http.get('/api/v1/providers/:provider/models', ({ params }) =>
        HttpResponse.json(params.provider === 'nvidia' ? NIM_MODELS : []),
      ),
    )
    const user = await reachCombos()
    await openPicker(user)
    await user.click(await screen.findByRole('button', { name: /nvidia/ }))
    expect(await screen.findByText(/deepseek-coder/)).toBeInTheDocument()
  })

  it('shows unknown capabilities as unknown, never as unsupported', async () => {
    mockRepo()
    const { NIM_MODELS } = await import('../test/server')
    server.use(
      http.get('/api/v1/providers/:provider/models', ({ params }) =>
        HttpResponse.json(params.provider === 'nvidia' ? NIM_MODELS : []),
      ),
    )
    const user = await reachCombos()
    await openPicker(user)
    await user.click(await screen.findByRole('button', { name: /nvidia/ }))

    // "no tools" would assert a capability we cannot read from the listing.
    expect(await screen.findByText(/tools unknown/)).toBeInTheDocument()
    expect(screen.queryByText(/· no tools/)).not.toBeInTheDocument()
    // And credit billing must not be dressed up as a verified free tier.
    expect(await screen.findByText(/bills credits rather than offering a free/)).toBeInTheDocument()
  })

  it('marks the baseline stale after commands are edited', async () => {
    mockRepo()
    const user = await reachReview()
    await user.click(await screen.findByText('review'))
    const test = await screen.findByLabelText('test')
    await user.clear(test)
    await user.type(test, 'pytest -x')
    await user.click(screen.getByRole('button', { name: /Save commands/ }))

    expect(await screen.findByText(/Commands changed since this baseline ran/)).toBeInTheDocument()
  })
})
