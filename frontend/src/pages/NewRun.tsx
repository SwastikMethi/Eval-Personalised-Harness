import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  FormControlLabel,
  Grid,
  Radio,
  RadioGroup,
  Step,
  StepLabel,
  Stepper,
  Table,
  TableBody,
  TableCell,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Analysis, Commit, HiddenTest } from '../api'
import { Empty, Mono, PageTitle, Panel, Stat } from '../components/primitives'
import { C, fonts } from '../theme'

const STEPS = ['Repository', 'Task', 'Configure & review'] as const

/** Only `test` is load-bearing. The backend skips a blank install/build/lint/
 *  typecheck outright, so presenting them as equal fields implies work the
 *  user does not need to do — most Python repos have no build step at all. */
const REQUIRED_COMMANDS = ['test'] as const
const OPTIONAL_COMMANDS = ['install', 'build', 'lint', 'typecheck'] as const

/** Free tier grants roughly 50 model requests a DAY, so the request budget —
 *  not wall-clock — decides whether a matrix is runnable today. */
const DAILY_FREE_REQUESTS = 50

export default function NewRun() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // step 1
  const [source, setSource] = useState<'local' | 'github'>('local')
  const [pathOrUrl, setPathOrUrl] = useState('')
  const [repoId, setRepoId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [commands, setCommands] = useState<Record<string, string>>({})
  const [framework, setFramework] = useState('')
  const [baselineStale, setBaselineStale] = useState(false)

  // step 2
  const [taskMode, setTaskMode] = useState<'commit' | 'describe'>('commit')
  const [shaToTask, setShaToTask] = useState<Record<string, string>>({})
  const [selectedShas, setSelectedShas] = useState<string[]>([])
  const [describedTaskIds, setDescribedTaskIds] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [hidden, setHidden] = useState<HiddenTest[]>([])

  // step 3
  const [harnesses, setHarnesses] = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [reps, setReps] = useState(1)
  const [budget, setBudget] = useState(8)
  const [setupOpen, setSetupOpen] = useState(false)
  // Free-only by default: of 400+ models on OpenRouter only ~14 are free, and
  // this account has no credits, so listing the rest is 400 ways to fail.
  const [showPaid, setShowPaid] = useState(false)
  const [modelFilter, setModelFilter] = useState('')

  const availableHarnesses = useQuery({ queryKey: ['harnesses'], queryFn: api.harnesses })
  const availableModels = useQuery({
    queryKey: ['models', showPaid],
    queryFn: () => api.models(!showPaid),
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
      runBaseline.mutate(id)
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
      setError(null)
      if (candidates > 0) {
        const candidateList = await api.hiddenTests(id)
        setHidden((prev) => [...prev, ...candidateList])
      }
    },
    onError: fail,
  })

  const describeTask = useMutation({
    mutationFn: () => api.createTask({ repository_id: repoId!, title, prompt }),
    onSuccess: ({ id }) => {
      setDescribedTaskIds((prev) => [...prev, id])
      setTitle('')
      setPrompt('')
      setError(null)
    },
    onError: fail,
  })

  const taskIds = useMemo(
    () => [...selectedShas.map((s) => shaToTask[s]).filter(Boolean), ...describedTaskIds],
    [selectedShas, shaToTask, describedTaskIds],
  )

  const launch = useMutation({
    mutationFn: async () => {
      // Pin exact model metadata per experiment so a model that later vanishes
      // fails its combination loudly instead of being silently substituted.
      for (const m of models) {
        try {
          await api.snapshotModel(m)
        } catch {
          /* snapshot is best-effort; pricing just stays unknown */
        }
      }
      const combinations = harnesses.flatMap((h) =>
        models.map((m) => ({ harness: h, provider: 'openrouter', model_id: m })),
      )
      return api.createExperiment({
        repository_id: repoId,
        name: `${harnesses.length}×${models.length} · ${new Date().toISOString().slice(0, 16)}`,
        task_ids: taskIds,
        combinations,
        repetitions: reps,
        config: { max_model_requests: budget, max_steps: budget, timeout_seconds: 1800 },
      })
    },
    onSuccess: ({ id }) => navigate(`/experiments/${id}`),
    onError: fail,
  })

  const testCommand = (commands.test ?? '').trim()
  const baseline = runBaseline.data
  const baselineBroken = baseline?.benchmarkable === false
  const needsAttention = Boolean(repoId) && (!testCommand || baselineBroken)

  // Open the setup panel by itself, but only when something genuinely needs
  // the user — otherwise it stays out of the way.
  useEffect(() => {
    if (needsAttention) setSetupOpen(true)
  }, [needsAttention])

  const runs = harnesses.length * models.length * taskIds.length * reps
  const requests = runs * budget
  const overDailyCap = requests > DAILY_FREE_REQUESTS

  const blockers: string[] = []
  if (taskIds.length === 0) blockers.push('pick at least one task')
  if (harnesses.length === 0) blockers.push('pick at least one harness')
  if (models.length === 0) blockers.push('pick at least one model')
  if (!testCommand) blockers.push('no test command — there is no correctness signal without one')
  if (baselineBroken) blockers.push('baseline could not establish a signal')

  const toggle = (list: string[], value: string, set: (v: string[]) => void) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  // Backend already sorts free + tool-capable first; this only narrows.
  const sortedModels = useMemo(() => {
    const q = modelFilter.trim().toLowerCase()
    const all = availableModels.data ?? []
    return q ? all.filter((m) => m.model_id.toLowerCase().includes(q)) : all
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

  return (
    <Box>
      <PageTitle
        title="New benchmark run"
        sub="Point it at a repository, pick what the agents should attempt, then choose which harness × model combinations to compare."
      />

      <Stepper activeStep={step} sx={{ mb: 4 }}>
        {STEPS.map((label, i) => (
          <Step key={label} completed={i < step}>
            <StepLabel
              onClick={() => i < step && setStep(i)}
              sx={{
                cursor: i < step ? 'pointer' : 'default',
                '& .MuiStepLabel-label': { fontSize: '0.82rem', fontWeight: 600 },
              }}
            >
              {label}
            </StepLabel>
          </Step>
        ))}
      </Stepper>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* ---------------------------------------------------------------- 1 */}
      {step === 0 && (
        <Panel label="Repository">
          <RadioGroup
            row
            value={source}
            onChange={(e) => setSource(e.target.value as 'local' | 'github')}
            sx={{ mb: 2 }}
          >
            <FormControlLabel value="local" control={<Radio size="small" />} label="Local path" />
            <FormControlLabel
              value="github"
              control={<Radio size="small" />}
              label="Public GitHub URL"
            />
          </RadioGroup>
          <TextField
            fullWidth
            value={pathOrUrl}
            onChange={(e) => setPathOrUrl(e.target.value)}
            placeholder={
              source === 'local' ? '/Users/you/Projects/your-repo' : 'https://github.com/owner/repo'
            }
            sx={{ mb: 1 }}
          />
          <Typography sx={{ color: C.faint, fontSize: '0.78rem', mb: 2, maxWidth: '72ch' }}>
            That is all that is needed to start. Languages, package managers and test commands are
            detected automatically, and a clean baseline runs in the background while you pick
            tasks — you can review and correct all of it on the last step.
          </Typography>
          <Button
            variant="contained"
            disabled={!pathOrUrl.trim() || addRepo.isPending}
            onClick={() => addRepo.mutate()}
            startIcon={addRepo.isPending ? <CircularProgress size={14} /> : null}
          >
            {addRepo.isPending ? 'Analyzing…' : 'Analyze repository'}
          </Button>
        </Panel>
      )}

      {/* ---------------------------------------------------------------- 2 */}
      {step === 1 && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Panel label="What should the agents attempt?">
              <ToggleButtonGroup
                exclusive
                size="small"
                value={taskMode}
                onChange={(_, v) => v && setTaskMode(v)}
                sx={{ mb: 2 }}
              >
                <ToggleButton value="commit">Replay a commit</ToggleButton>
                <ToggleButton value="describe">Describe a task</ToggleButton>
              </ToggleButtonGroup>

              {taskMode === 'commit' ? (
                <>
                  <Typography sx={{ color: C.dim, fontSize: '0.82rem', mb: 2, maxWidth: '68ch' }}>
                    Tick up to five. Each commit's <strong>parent</strong> becomes the starting
                    state and the commit itself is the known answer — the agent only ever sees a
                    fresh snapshot at the parent, with no remotes and no future history. This is
                    the strongest signal available, because the real tests shipped with the commit.
                  </Typography>
                  {commits.isLoading && <CircularProgress size={16} />}
                  <Box sx={{ maxHeight: 380, overflowY: 'auto' }}>
                    {(commits.data ?? [])
                      .filter((c: Commit) => c.parent)
                      .slice(0, 50)
                      .map((c: Commit) => (
                        <FormControlLabel
                          key={c.sha}
                          control={
                            <Checkbox
                              size="small"
                              checked={selectedShas.includes(c.sha)}
                              disabled={pickCommit.isPending}
                              onChange={(e) => {
                                if (e.target.checked) pickCommit.mutate(c.sha)
                                else setSelectedShas((p) => p.filter((s) => s !== c.sha))
                              }}
                            />
                          }
                          label={
                            <Box sx={{ minWidth: 0 }}>
                              <Mono color={C.text} size="0.76rem">
                                {c.subject.slice(0, 72)}
                              </Mono>
                              <Typography
                                sx={{ fontFamily: fonts.mono, fontSize: '0.64rem', color: C.faint }}
                              >
                                {c.sha.slice(0, 8)} · {c.author} · {c.date.slice(0, 10)}
                              </Typography>
                            </Box>
                          }
                          sx={{ display: 'flex', mb: 0.5, alignItems: 'flex-start' }}
                        />
                      ))}
                  </Box>
                  {!commits.isLoading && (commits.data ?? []).length === 0 && (
                    <Empty>No commits with a parent found — describe a task instead.</Empty>
                  )}
                </>
              ) : (
                <>
                  <TextField
                    fullWidth
                    label="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    sx={{ mb: 1.5 }}
                  />
                  <TextField
                    fullWidth
                    multiline
                    minRows={4}
                    label="prompt"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Describe the change precisely. The agent sees only this and the repository."
                    sx={{ mb: 2 }}
                  />
                  <Button
                    variant="outlined"
                    disabled={!title.trim() || !prompt.trim() || describeTask.isPending}
                    onClick={() => describeTask.mutate()}
                  >
                    Add task
                  </Button>
                </>
              )}

              <Divider sx={{ my: 2.5 }} />
              <Typography variant="overline">selected · {taskIds.length}</Typography>
              {taskIds.length === 0 ? (
                <Empty>Nothing selected yet.</Empty>
              ) : (
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {selectedShas.map((s) => (
                    <Chip key={s} size="small" variant="outlined" label={s.slice(0, 8)} />
                  ))}
                  {describedTaskIds.map((id) => (
                    <Chip key={id} size="small" variant="outlined" label="described" />
                  ))}
                </Box>
              )}
              <Box sx={{ mt: 2 }}>
                <Button
                  variant="contained"
                  disabled={taskIds.length === 0}
                  onClick={() => setStep(2)}
                >
                  Continue
                </Button>
              </Box>
            </Panel>
          </Grid>

          <Grid size={{ xs: 12, md: 5 }}>
            <Panel label="Hidden test candidates">
              <Typography sx={{ color: C.dim, fontSize: '0.8rem', mb: 1.5 }}>
                Extracted from the target commit and run only <em>after</em> the agent stops.
                Low-confidence candidates start unapproved — nothing runs without your say-so.
              </Typography>
              {hidden.length === 0 ? (
                <Empty>None yet. Tick a commit that adds tests to see candidates.</Empty>
              ) : (
                hidden.map((h) => (
                  <Box key={h.id} sx={{ mb: 1.5, pb: 1.5, borderBottom: `1px solid ${C.lineSoft}` }}>
                    <FormControlLabel
                      control={
                        <Checkbox
                          size="small"
                          checked={h.approved === true}
                          onChange={async (e) => {
                            await api.approveHiddenTest(h.id, e.target.checked)
                            setHidden((prev) =>
                              prev.map((x) =>
                                x.id === h.id ? { ...x, approved: e.target.checked } : x,
                              ),
                            )
                          }}
                        />
                      }
                      label={
                        <Mono size="0.76rem" color={C.text}>
                          {h.relpath}
                        </Mono>
                      }
                    />
                    <Typography
                      sx={{ fontFamily: fonts.mono, fontSize: '0.68rem', color: C.faint, pl: 4 }}
                    >
                      {h.change_type} · confidence {h.confidence}
                      {h.reject_reason ? ` · ${h.reject_reason}` : ''}
                    </Typography>
                  </Box>
                ))
              )}
            </Panel>
          </Grid>
        </Grid>
      )}

      {/* ---------------------------------------------------------------- 3 */}
      {step === 2 && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Panel label="Harnesses" sx={{ mb: 2 }}>
              {(availableHarnesses.data ?? []).map((h) => (
                <FormControlLabel
                  key={h.name}
                  control={
                    <Checkbox
                      size="small"
                      checked={harnesses.includes(h.name)}
                      onChange={() => toggle(harnesses, h.name, setHarnesses)}
                    />
                  }
                  label={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Mono color={C.text}>{h.name}</Mono>
                      <Typography
                        sx={{ fontFamily: fonts.mono, fontSize: '0.65rem', color: C.faint }}
                      >
                        {h.sandboxed ? 'sandboxed' : 'in-process'}
                      </Typography>
                    </Box>
                  }
                  sx={{ display: 'flex', mb: 0.5 }}
                />
              ))}
            </Panel>

            <Panel
              label={`Models · ${sortedModels.length}`}
              action={
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={showPaid}
                      onChange={(e) => {
                        setShowPaid(e.target.checked)
                        setModels([])
                      }}
                    />
                  }
                  label={
                    <Typography sx={{ fontSize: '0.75rem', color: C.dim }}>
                      include paid
                    </Typography>
                  }
                />
              }
            >
              {availableModels.isLoading && <CircularProgress size={16} />}
              {availableModels.isError && (
                <Alert severity="warning">
                  Could not list models — check OPENROUTER_API_KEY in .env.
                </Alert>
              )}
              {showPaid && (
                <Alert severity="warning" sx={{ mb: 1.5 }}>
                  Paid models need OpenRouter credits, and spec §2 puts closed-source models out of
                  scope — this tool benchmarks open-weight stacks. Open-weight-but-paid models
                  (Kimi, GLM) are fine if you have credits.
                </Alert>
              )}
              <TextField
                fullWidth
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
                placeholder="filter by name…"
                sx={{ mb: 1.5 }}
              />
              <Box sx={{ maxHeight: 300, overflowY: 'auto' }}>
                {sortedModels.map((m) => (
                  <FormControlLabel
                    key={m.model_id}
                    control={
                      <Checkbox
                        size="small"
                        checked={models.includes(m.model_id)}
                        onChange={() => toggle(models, m.model_id, setModels)}
                      />
                    }
                    label={
                      <Box>
                        <Mono color={C.text} size="0.76rem">
                          {m.model_id}
                        </Mono>
                        <Typography
                          sx={{ fontFamily: fonts.mono, fontSize: '0.64rem', color: C.faint }}
                        >
                          {m.context_length ? `${(m.context_length / 1000).toFixed(0)}k ctx` : ''}
                          {m.is_free ? ' · free' : ' · paid'}
                          {m.supports_tools ? ' · tools' : ' · no tools'}
                        </Typography>
                      </Box>
                    }
                    sx={{ display: 'flex', mb: 0.5 }}
                  />
                ))}
              </Box>
            </Panel>
          </Grid>

          <Grid size={{ xs: 12, md: 5 }}>
            <Panel label="Matrix" sx={{ mb: 2 }}>
              <Grid container spacing={2} sx={{ mb: 2 }}>
                <Grid size={6}>
                  <TextField
                    fullWidth
                    type="number"
                    label="repetitions"
                    value={reps}
                    onChange={(e) => setReps(Math.max(1, Number(e.target.value)))}
                  />
                </Grid>
                <Grid size={6}>
                  <TextField
                    fullWidth
                    type="number"
                    label="requests / run"
                    value={budget}
                    onChange={(e) => setBudget(Math.max(1, Number(e.target.value)))}
                  />
                </Grid>
              </Grid>

              <Table size="small" sx={{ mb: 2 }}>
                <TableBody>
                  {[
                    ['harnesses', harnesses.length],
                    ['models', models.length],
                    ['tasks', taskIds.length],
                    ['repetitions', reps],
                  ].map(([k, v]) => (
                    <TableRow key={String(k)}>
                      <TableCell
                        sx={{
                          border: 0,
                          py: 0.4,
                          pl: 0,
                          color: C.faint,
                          fontFamily: fonts.mono,
                          fontSize: '0.72rem',
                        }}
                      >
                        {k}
                      </TableCell>
                      <TableCell align="right" sx={{ border: 0, py: 0.4, pr: 0 }}>
                        <Mono color={C.text}>{v}</Mono>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <Divider sx={{ mb: 2 }} />
              <Grid container spacing={2}>
                <Grid size={6}>
                  <Stat label="total runs" value={runs} color={runs ? C.live : C.faint} />
                </Grid>
                <Grid size={6}>
                  <Stat
                    label="model requests"
                    value={requests}
                    color={overDailyCap ? C.warn : C.pass}
                    hint={`free tier ≈ ${DAILY_FREE_REQUESTS}/day`}
                  />
                </Grid>
              </Grid>

              {reps < 3 && runs > 0 && (
                <Alert severity="info" sx={{ mt: 2 }}>
                  Under 3 repetitions every result is flagged statistically weak. Fine for a smoke
                  test; not enough for a reliability claim.
                </Alert>
              )}
              {overDailyCap && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  This needs {requests} requests — more than a free-tier day. Runs that hit the
                  limit are parked as rate-limited and resume automatically, so the matrix takes
                  longer rather than failing.
                </Alert>
              )}
            </Panel>

            {/* Collapsed by default; opens itself only when it needs the user. */}
            <Panel sx={{ mb: 2 }}>
              <Box
                onClick={() => setSetupOpen((v) => !v)}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  gap: 2,
                }}
              >
                <Box>
                  <Typography variant="overline">setup</Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Mono size="0.76rem" color={needsAttention ? C.warn : C.dim}>
                      {[
                        analysis?.languages?.[0] ?? 'unknown',
                        framework || 'no framework',
                        baselineLabel,
                      ].join(' · ')}
                    </Mono>
                    {runBaseline.isPending && <CircularProgress size={11} />}
                  </Box>
                </Box>
                <Mono size="0.7rem" color={C.live}>
                  {setupOpen ? 'hide' : 'review'}
                </Mono>
              </Box>

              {/* unmountOnExit: collapsed fields stay in the DOM otherwise,
                  so they remain tab-focusable while invisible. */}
              <Collapse in={setupOpen} unmountOnExit>
                <Divider sx={{ my: 2 }} />

                <Typography variant="overline">commands</Typography>
                <TextField
                  fullWidth
                  label="test"
                  value={commands.test ?? ''}
                  onChange={(e) => setCommands({ ...commands, test: e.target.value })}
                  error={!testCommand}
                  helperText={
                    testCommand
                      ? 'how the evaluator runs your tests'
                      : 'required — without it there is no correctness signal'
                  }
                  sx={{ mb: 2, mt: 1 }}
                />
                {OPTIONAL_COMMANDS.map((field) => (
                  <TextField
                    key={field}
                    fullWidth
                    label={`${field} (optional)`}
                    value={commands[field] ?? ''}
                    onChange={(e) => setCommands({ ...commands, [field]: e.target.value })}
                    helperText="leave blank to skip"
                    sx={{ mb: 1.5 }}
                  />
                ))}
                <TextField
                  fullWidth
                  label="test framework"
                  value={framework}
                  onChange={(e) => setFramework(e.target.value)}
                  helperText="pytest, vitest, jest… decides how test output is parsed"
                  sx={{ mb: 2 }}
                />
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => saveCommands.mutate()}
                  disabled={saveCommands.isPending}
                  sx={{ mb: 2 }}
                >
                  Save commands
                </Button>

                <Divider sx={{ my: 2 }} />
                <Typography variant="overline">baseline</Typography>
                <Typography sx={{ color: C.dim, fontSize: '0.78rem', mb: 1.5, maxWidth: '60ch' }}>
                  Runs your commands on a clean snapshot before any agent touches the repo, so
                  failures that already existed are never blamed on an agent.
                </Typography>
                {baseline && (
                  <Grid container spacing={2} sx={{ mb: 1.5 }}>
                    {Object.entries(baseline.steps).map(([name, s]) => (
                      <Grid size="auto" key={name}>
                        <Stat
                          label={name}
                          value={s.exit_code === 0 ? 'pass' : `exit ${s.exit_code}`}
                          color={s.exit_code === 0 ? C.pass : C.warn}
                        />
                      </Grid>
                    ))}
                    <Grid size="auto">
                      <Stat label="baseline tests" value={baseline.test_case_count} />
                    </Grid>
                  </Grid>
                )}
                {baselineStale && (
                  <Alert severity="info" sx={{ mb: 1.5 }}>
                    Commands changed since this baseline ran — re-run it so regressions are measured
                    against the right starting point.
                  </Alert>
                )}
                {baselineBroken && (
                  <Alert severity="error" sx={{ mb: 1.5 }}>
                    Baseline could not establish a signal — install or build failed, or tests could
                    not be collected. Fix the commands above and re-run.
                  </Alert>
                )}
                {baseline?.warn && !baselineBroken && (
                  <Alert severity="warning" sx={{ mb: 1.5 }}>
                    Baseline is partially failing. You can proceed — those failures are excluded
                    from regression counting.
                  </Alert>
                )}
                <Button
                  size="small"
                  variant="outlined"
                  disabled={runBaseline.isPending || !repoId}
                  onClick={() => runBaseline.mutate(repoId!)}
                >
                  {runBaseline.isPending ? 'Running…' : 'Re-run baseline'}
                </Button>
              </Collapse>
            </Panel>

            <Button
              fullWidth
              size="large"
              variant="contained"
              disabled={blockers.length > 0 || launch.isPending}
              onClick={() => launch.mutate()}
              startIcon={launch.isPending ? <CircularProgress size={14} /> : null}
            >
              {launch.isPending ? 'Starting…' : `Start ${runs} run${runs === 1 ? '' : 's'}`}
            </Button>
            {/* Every blocker, not just the first — hiding the rest makes the
                button feel like it never unlocks. */}
            {blockers.map((reason) => (
              <Typography
                key={reason}
                sx={{ fontFamily: fonts.mono, fontSize: '0.7rem', color: C.warn, mt: 0.75 }}
              >
                {reason}
              </Typography>
            ))}
          </Grid>
        </Grid>
      )}
    </Box>
  )
}
