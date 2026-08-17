import { useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { Analysis, Commit, HiddenTest, ProposedTask } from '../../api'
import { useStage } from '../../stages'

/**
 * All wizard state and every mutation, in one place.
 *
 * The four screens share almost all of this — a commit ticked on Tasks changes
 * the matrix arithmetic on Review — so the state has to live above them. Keeping
 * it in a hook rather than a context is deliberate: there is exactly one
 * consumer tree, and a context would add indirection without removing any
 * coupling.
 *
 * The logic here is carried over unchanged from the previous single-file
 * wizard. Only the rendering was rebuilt.
 */

export const STEPS = ['Repository', 'Tasks', 'Agent stacks', 'Review'] as const
export type Step = 0 | 1 | 2 | 3

/**
 * One harness against one model on one provider — the unit being benchmarked.
 *
 * The provider belongs to the stack, not to the experiment: the same model
 * served by NVIDIA and by OpenRouter is two different stacks, and telling them
 * apart is exactly the kind of question this tool exists to answer.
 */
export interface Stack {
  harness: string
  provider: string
  model_id: string
}

export const stackKey = (s: Stack) => `${s.harness}|${s.provider}|${s.model_id}`

/** Only `test` is load-bearing. The backend skips a blank install/build/lint/
 *  typecheck outright, so presenting them as equal fields implies work the
 *  user does not need to do — most Python repos have no build step at all. */
export const REQUIRED_COMMANDS = ['test'] as const
export const OPTIONAL_COMMANDS = ['install', 'build', 'lint', 'typecheck'] as const

/** Free tier grants roughly 50 model requests a DAY, so the request budget —
 *  not wall-clock — decides whether a matrix is runnable today. */
export const DAILY_FREE_REQUESTS = 50

export function useWizard() {
  const navigate = useNavigate()
  // The position is shared with the rail, which renders the same progress from
  // outside the router. Everything else below stays local to the wizard.
  const { step, setStep } = useStage()
  const [error, setError] = useState<string | null>(null)

  // Repository
  const [source, setSource] = useState<'local' | 'github'>('local')
  const [pathOrUrl, setPathOrUrl] = useState('')
  const [repoId, setRepoId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [commands, setCommands] = useState<Record<string, string>>({})
  const [framework, setFramework] = useState('')
  const [baselineStale, setBaselineStale] = useState(false)

  // Tasks.
  // Comprehension tasks need no test suite, no patch and no environment
  // repair — which is why they are the mode that works on a repo whose own
  // tests cannot distinguish a correct patch from an empty one.
  const [taskMode, setTaskMode] = useState<'commit' | 'comprehension' | 'describe'>('commit')
  const [proposed, setProposed] = useState<ProposedTask[]>([])
  const [shaToTask, setShaToTask] = useState<Record<string, string>>({})
  const [selectedShas, setSelectedShas] = useState<string[]>([])
  // Two lists, not one. They used to share `describedTaskIds`, which made
  // "are all the selected tasks comprehension tasks?" unanswerable — and that
  // is exactly the question that decides whether a baseline is needed at all.
  const [theoryTaskIds, setTheoryTaskIds] = useState<string[]>([])
  const [describedTaskIds, setDescribedTaskIds] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [hidden, setHidden] = useState<HiddenTest[]>([])
  // Of 11 commits on a typical small repo, 5 are README edits and 2 are merges.
  // The model's shortlist is the default; the raw log stays one click away so a
  // bad nomination never traps the user.
  const [showAllCommits, setShowAllCommits] = useState(false)

  // Stacks + review.
  //
  // A stack is the thing being compared, so it is stored as one. Two lists
  // multiplied together could only ever express a full grid: you could not run
  // `mini-swe-agent × nemotron` against `smolagents × gpt-oss` and nothing
  // else, and because the provider was a single value for the whole matrix,
  // every model had to come from the same one.
  const [stacks, setStacks] = useState<Stack[]>([])
  // What the picker has ticked right now. Short-lived, and separate from
  // `stacks` so that closing the dialog adds to the selection rather than
  // replacing it.
  const [draftHarnesses, setDraftHarnesses] = useState<string[]>([])
  const [draftModels, setDraftModels] = useState<string[]>([])
  const [reps, setReps] = useState(1)
  // Two knobs, not one. They used to be the same number sent as both
  // max_model_requests and max_steps, which meant you could not bound spend
  // without also bounding how much work the agent was allowed to attempt.
  const [budget, setBudget] = useState(8)
  const [steps, setSteps] = useState(50)
  // Uncapped lets the agent stop when it is finished rather than when it runs
  // out of allowance. Safe because a run that times out having produced a patch
  // is still graded — but only sensible where tokens, not a daily request
  // quota, are the constraint, so it stays off for free-tier providers.
  const [uncapped, setUncapped] = useState(false)
  const [setupOpen, setSetupOpen] = useState(false)
  // Free-only by default: of 400+ models on OpenRouter only ~14 are free, and
  // this account has no credits, so listing the rest is 400 ways to fail.
  const [showPaid, setShowPaid] = useState(false)
  const [modelFilter, setModelFilter] = useState('')
  // Which catalogue the picker is browsing. NOT the experiment's provider —
  // each stack carries its own, so one matrix can mix NVIDIA and OpenRouter.
  const [provider, setProvider] = useState('openrouter')

  const availableHarnesses = useQuery({ queryKey: ['harnesses'], queryFn: api.harnesses })
  const providers = useQuery({ queryKey: ['providers'], queryFn: api.providers })
  const activeProvider = providers.data?.find((p) => p.name === provider)
  // NIM bills credits — nothing there is a free per-token tier, so a
  // "free only" filter would return an empty list.
  const freeOnly = activeProvider?.has_free_tier === false ? false : !showPaid
  const availableModels = useQuery({
    queryKey: ['models', provider, freeOnly],
    queryFn: () => api.models(provider, freeOnly),
    staleTime: 300_000,
  })
  const commits = useQuery({
    queryKey: ['commits', repoId],
    queryFn: () => api.commits(repoId!),
    enabled: Boolean(repoId),
  })

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e))

  // Runs in the background while the user picks tasks — install + the test
  // suite is slow, and blocking a whole wizard step on it buys nothing.
  const runBaseline = useMutation({
    mutationFn: (id: string) => api.baseline(id),
    onSuccess: () => setBaselineStale(false),
  })

  const addRepo = useMutation({
    mutationFn: async () => {
      const name = pathOrUrl.replace(/\/+$/, '').split('/').pop() || 'repository'
      const { id } = await api.addRepository({ name, source, path_or_url: pathOrUrl })
      await api.analyze(id)
      return { id, detail: await api.analysis(id) }
    },
    onSuccess: ({ id, detail }) => {
      setRepoId(id)
      setAnalysis(detail)
      const next: Record<string, string> = {}
      for (const f of [...REQUIRED_COMMANDS, ...OPTIONAL_COMMANDS]) {
        next[f] = detail.commands?.[f] ?? ''
      }
      setCommands(next)
      setFramework(detail.commands?.test_framework ?? '')
      setError(null)
      setStep(1)
      // No baseline here. It used to fire on registration, before the task type
      // was known, so a comprehension-only run paid for a container — and on a
      // repo whose install does not work in the sandbox, paid for it failing.
      // `ensureBaseline` starts it the moment a task is picked that needs one.
    },
    onError: fail,
  })

  const saveCommands = useMutation({
    mutationFn: async () => {
      const payload: Record<string, string | null> = { test_framework: framework || null }
      for (const f of [...REQUIRED_COMMANDS, ...OPTIONAL_COMMANDS]) {
        payload[f] = commands[f]?.trim() || null
      }
      await api.updateCommands(repoId!, payload)
    },
    onSuccess: () => setBaselineStale(true),
    onError: fail,
  })

  /**
   * Start the baseline, once, for task kinds that are graded by running tests.
   *
   * Commit and user-defined tasks need it: pre-existing failures must not be
   * counted as agent regressions. Comprehension tasks never call this.
   */
  const ensureBaseline = useCallback(() => {
    if (!repoId || runBaseline.isPending || runBaseline.data) return
    runBaseline.mutate(repoId)
  }, [repoId, runBaseline])

  /** Tick a commit → create its task once and cache it, so re-ticking is free
   *  and hidden-test candidates load immediately. */
  const pickCommit = useMutation({
    mutationFn: async (sha: string) => {
      if (shaToTask[sha]) return { sha, id: shaToTask[sha], candidates: 0 }
      const res = await api.taskFromCommit({ repository_id: repoId!, sha })
      return { sha, id: res.id, candidates: res.hidden_test_candidates }
    },
    onSuccess: async ({ sha, id, candidates }) => {
      setShaToTask((prev) => ({ ...prev, [sha]: id }))
      setSelectedShas((prev) => (prev.includes(sha) ? prev : [...prev, sha]))
      // This task is graded by running the suite, so the baseline is needed.
      ensureBaseline()
      setError(null)
      if (candidates > 0) {
        const candidateList = await api.hiddenTests(id)
        setHidden((prev) => [...prev, ...candidateList])
      }
    },
    onError: fail,
  })

  /** One request per press. Fills the fields as editable suggestions — never
   *  saved, never applied silently; the baseline then verifies them.
   *
   *  The boolean says whether a person asked for this. The same request also
   *  fires automatically to shortlist commits, and that one must NOT throw the
   *  setup panel open — the panel's whole contract is that it appears only when
   *  something needs the user. */
  const askAi = useMutation({
    mutationFn: (_requestedByUser: boolean) => api.suggest(repoId!),
    onSuccess: (s, requestedByUser) => {
      const next = { ...commands }
      for (const f of [...REQUIRED_COMMANDS, ...OPTIONAL_COMMANDS]) {
        next[f] = s.commands[f] ?? ''
      }
      setCommands(next)
      if (s.commands.test_framework) setFramework(s.commands.test_framework)
      if (requestedByUser) setSetupOpen(true)
      setBaselineStale(true)
      setError(null)
    },
    onError: fail,
  })
  const suggestion = askAi.data

  /** Decides HOW this repo can be evaluated and proves it by executing a
   *  baseline. Slower than "Suggest with AI" because it actually runs the
   *  commands — which is the point: it answers "can this repo be scored at
   *  all" BEFORE a matrix spends credits, rather than after every run comes
   *  back INSUFFICIENT_EVALUATION_SIGNAL. */
  const decideStrategy = useMutation({
    mutationFn: () => api.evaluationStrategy(repoId!),
    onSuccess: (d) => {
      const next = { ...commands }
      for (const f of [...REQUIRED_COMMANDS, ...OPTIONAL_COMMANDS]) {
        if (d.commands[f] !== undefined) next[f] = d.commands[f] ?? ''
      }
      setCommands(next)
      if (d.commands.test_framework) setFramework(d.commands.test_framework)
      setSetupOpen(true)
      // The analyzer already ran the baseline, so the commands are verified —
      // but leave the user free to re-run it after any edit of their own.
      setBaselineStale(false)
      setError(null)
    },
    onError: fail,
  })
  const strategy = decideStrategy.data

  /** Ask the analyzer for comprehension questions and the rubric each will be
   *  graded against. The tasks are created server-side so they tick like
   *  commits; the rubric is shown before launch so a low score can be checked
   *  against what was actually asked for. */
  const proposeTasks = useMutation({
    mutationFn: () => api.proposeTasks(repoId!),
    onSuccess: ({ tasks }) => {
      setProposed(tasks)
      setError(null)
    },
    onError: fail,
  })

  const describeTask = useMutation({
    mutationFn: () => api.createTask({ repository_id: repoId!, title, prompt }),
    onSuccess: ({ id }) => {
      setDescribedTaskIds((prev) => [...prev, id])
      ensureBaseline()
      setTitle('')
      setPrompt('')
      setError(null)
    },
    onError: fail,
  })

  const taskIds = useMemo(
    () => [
      ...selectedShas.map((s) => shaToTask[s]).filter(Boolean),
      ...theoryTaskIds,
      ...describedTaskIds,
    ],
    [selectedShas, shaToTask, theoryTaskIds, describedTaskIds],
  )

  /**
   * Every selected task is a comprehension task.
   *
   * Those are graded against a rubric by reading the repository — no test
   * suite, no patch, no dependency install. A baseline would prove nothing and
   * can fail for reasons that have no bearing on the result.
   */
  const theoryOnly =
    taskIds.length > 0 && selectedShas.length === 0 && describedTaskIds.length === 0

  /** Ask for the shortlist as soon as the user reaches the task step. One
   *  request, reused by the setup panel on the next step — the model reads the
   *  repository once, not once per thing we want from it. */
  useEffect(() => {
    if (step === 1 && repoId && !askAi.data && !askAi.isPending) askAi.mutate(false)
  }, [step, repoId, askAi])

  /** The shortlist, restored to full commit metadata. Nominations carry the
   *  sha, subject, parent and the model's reason; author and date come from
   *  the git log we already fetched. */
  const nominated = useMemo(() => {
    const byS = new Map((commits.data ?? []).map((c: Commit) => [c.sha, c]))
    return (suggestion?.commits ?? [])
      .map((n) => ({ ...byS.get(n.sha), ...n }))
      .filter((c) => c.parent)
  }, [suggestion, commits.data])

  const usingShortlist = !showAllCommits && nominated.length > 0
  const commitList = usingShortlist
    ? nominated
    : (commits.data ?? []).filter((c: Commit) => c.parent).slice(0, 50)

  /** The slow step, run once per selected commit: rewrite the prompt, and
   *  generate a hidden test when the commit shipped none — each proven to fail
   *  before the fix and pass after it before it is offered for approval. */
  const prepare = useMutation({
    mutationFn: async () => {
      await api.prepareTests(repoId!)
      const reports = []
      for (const sha of selectedShas) {
        const taskId = shaToTask[sha]
        if (taskId) reports.push(await api.prepareTask(taskId, sha))
      }
      const lists = await Promise.all(
        selectedShas
          .map((s) => shaToTask[s])
          .filter(Boolean)
          .map(api.hiddenTests),
      )
      return { reports, candidates: lists.flat() }
    },
    onSuccess: ({ candidates }) => {
      setHidden(candidates)
      setError(null)
    },
    onError: fail,
  })

  const launch = useMutation({
    mutationFn: async () => {
      // Pin exact model metadata per experiment so a model that later vanishes
      // fails its combination loudly instead of being silently substituted.
      // Each against ITS OWN provider — the same model id can exist on two.
      for (const s of stacks) {
        try {
          await api.snapshotModel(s.provider, s.model_id)
        } catch {
          /* snapshot is best-effort; pricing just stays unknown */
        }
      }
      return api.createExperiment({
        repository_id: repoId,
        // "2×1" described a grid. The selection is no longer necessarily one.
        name: `${stacks.length} stack${stacks.length === 1 ? '' : 's'} · ${new Date()
          .toISOString()
          .slice(0, 16)}`,
        task_ids: taskIds,
        combinations: stacks,
        repetitions: reps,
        config: {
          // null is the wire form of "uncapped" — the backend only applies its
          // default when the key is absent, so this must be sent explicitly.
          max_model_requests: uncapped ? null : budget,
          max_steps: steps,
          timeout_seconds: 1800,
        },
      })
    },
    onSuccess: ({ id }) => navigate(`/experiments/${id}`),
    onError: fail,
  })

  const testCommand = (commands.test ?? '').trim()
  const baseline = runBaseline.data
  const baselineBroken = baseline?.benchmarkable === false
  const needsAttention = Boolean(repoId) && !theoryOnly && (!testCommand || baselineBroken)

  // Open the setup panel by itself, but only when something genuinely needs
  // the user — otherwise it stays out of the way.
  useEffect(() => {
    if (needsAttention) setSetupOpen(true)
  }, [needsAttention])

  const runs = stacks.length * taskIds.length * reps
  const requests = runs * budget
  const overDailyCap = requests > DAILY_FREE_REQUESTS

  const blockers: string[] = []
  if (taskIds.length === 0) blockers.push('pick at least one task')
  if (stacks.length === 0) blockers.push('add at least one agent stack')
  // Neither applies to a comprehension-only matrix: the rubric is the signal.
  if (!theoryOnly && !testCommand)
    blockers.push('no test command — there is no correctness signal without one')
  if (!theoryOnly && baselineBroken) blockers.push('baseline could not establish a signal')

  // Backend already sorts free + tool-capable first; this only narrows.
  const sortedModels = useMemo(() => {
    const q = modelFilter.trim().toLowerCase()
    const all = availableModels.data ?? []
    if (!q) return all
    // Match the display name too. The list shows both, so filtering on the id
    // alone made a search for the name the user can see return nothing.
    return all.filter(
      (m) =>
        m.model_id.toLowerCase().includes(q) ||
        (m.display_name ?? '').toLowerCase().includes(q),
    )
  }, [availableModels.data, modelFilter])

  const baselineLabel = runBaseline.isPending
    ? 'baseline running…'
    : baselineBroken
      ? 'baseline failed'
      : baseline?.warn
        ? 'baseline passed with warnings'
        : baseline
          ? 'baseline passed'
          : 'baseline not run'

  const toggle = (list: string[], value: string, set: (v: string[]) => void) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  /** What the picker's current ticks would contribute. */
  const draftStacks: Stack[] = draftHarnesses.flatMap((harness) =>
    draftModels.map((model_id) => ({ harness, provider, model_id })),
  )

  /**
   * Fold the picker's ticks into the selection.
   *
   * Crossing within one visit is deliberate — a full sweep should still be one
   * pass — but visits ADD rather than replace, which is what makes an arbitrary
   * set of pairs expressible at all. Deduplicated on the whole triple, so the
   * same model from two providers survives as two stacks while the same stack
   * twice stays one.
   */
  const addDraftStacks = () => {
    setStacks((prev) => {
      const seen = new Set(prev.map(stackKey))
      return [...prev, ...draftStacks.filter((s) => !seen.has(stackKey(s)))]
    })
    setDraftHarnesses([])
    setDraftModels([])
  }

  const removeStack = (key: string) =>
    setStacks((prev) => prev.filter((s) => stackKey(s) !== key))

  /**
   * Whether any chosen stack is served by a free tier.
   *
   * Uncapped used to be gated on the single global provider. With a mixed
   * matrix that would let one OpenRouter stack ride along uncapped inside an
   * otherwise credit-billed run and quietly spend the daily quota.
   */
  const anyFreeTier = stacks.some(
    (s) => (providers.data ?? []).find((p) => p.name === s.provider)?.has_free_tier !== false,
  )

  return {
    step,
    setStep,
    error,
    setError,

    source,
    setSource,
    pathOrUrl,
    setPathOrUrl,
    repoId,
    analysis,
    commands,
    setCommands,
    framework,
    setFramework,
    baselineStale,

    taskMode,
    setTaskMode,
    proposed,
    selectedShas,
    setSelectedShas,
    theoryTaskIds,
    setTheoryTaskIds,
    describedTaskIds,
    setDescribedTaskIds,
    title,
    setTitle,
    prompt,
    setPrompt,
    hidden,
    setHidden,
    showAllCommits,
    setShowAllCommits,

    stacks,
    setStacks,
    draftHarnesses,
    setDraftHarnesses,
    draftModels,
    setDraftModels,
    draftStacks,
    addDraftStacks,
    removeStack,
    anyFreeTier,
    reps,
    setReps,
    budget,
    setBudget,
    steps,
    setSteps,
    uncapped,
    setUncapped,
    setupOpen,
    setSetupOpen,
    showPaid,
    setShowPaid,
    modelFilter,
    setModelFilter,
    provider,
    setProvider,

    availableHarnesses,
    providers,
    activeProvider,
    availableModels,
    commits,

    addRepo,
    saveCommands,
    pickCommit,
    askAi,
    suggestion,
    decideStrategy,
    strategy,
    proposeTasks,
    describeTask,
    prepare,
    launch,
    runBaseline,

    taskIds,
    nominated,
    usingShortlist,
    commitList,
    testCommand,
    baseline,
    baselineBroken,
    needsAttention,
    theoryOnly,
    ensureBaseline,
    runs,
    requests,
    overDailyCap,
    blockers,
    sortedModels,
    baselineLabel,
    toggle,
  }
}

export type Wizard = ReturnType<typeof useWizard>
