import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Divider,
  FormControlLabel,
  Grid,
  MenuItem,
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
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Analysis, BaselineOutcome, Commit, HiddenTest } from '../api'
import { Empty, Mono, PageTitle, Panel, Stat } from '../components/primitives'
import { C, fonts } from '../theme'

const STEPS = ['Repository', 'Commands', 'Baseline', 'Task', 'Matrix'] as const
const COMMAND_FIELDS = ['install', 'build', 'test', 'lint', 'typecheck'] as const

/** Free tier grants roughly 50 model requests a DAY, so the request budget —
 *  not wall-clock — is what decides whether a matrix is runnable today. */
const DAILY_FREE_REQUESTS = 50

export default function NewRun() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // step 1
  const [source, setSource] = useState<'local' | 'github'>('local')
  const [pathOrUrl, setPathOrUrl] = useState('')
  const [repoId, setRepoId] = useState<string | null>(null)
  // step 2
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [commands, setCommands] = useState<Record<string, string>>({})
  const [framework, setFramework] = useState('')
  // step 3
  const [baseline, setBaseline] = useState<BaselineOutcome | null>(null)
  // step 4
  const [taskMode, setTaskMode] = useState<'defined' | 'commit'>('defined')
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [sha, setSha] = useState('')
  const [taskIds, setTaskIds] = useState<string[]>([])
  const [hidden, setHidden] = useState<HiddenTest[]>([])
  // step 5
  const [harnesses, setHarnesses] = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [reps, setReps] = useState(1)
  const [budget, setBudget] = useState(8)

  const availableHarnesses = useQuery({ queryKey: ['harnesses'], queryFn: api.harnesses })
  const availableModels = useQuery({
    queryKey: ['models'],
    queryFn: () => api.models(false),
    staleTime: 300_000,
  })
  const commits = useQuery({
    queryKey: ['commits', repoId],
    queryFn: () => api.commits(repoId!),
    enabled: Boolean(repoId) && taskMode === 'commit',
  })

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e))

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
      for (const f of COMMAND_FIELDS) next[f] = detail.commands?.[f] ?? ''
      setCommands(next)
      setFramework(detail.commands?.test_framework ?? '')
      setError(null)
      setStep(1)
    },
    onError: fail,
  })

  const saveCommands = useMutation({
    mutationFn: async () => {
      const payload: Record<string, string | null> = { test_framework: framework || null }
      for (const f of COMMAND_FIELDS) payload[f] = commands[f]?.trim() || null
      await api.updateCommands(repoId!, payload)
    },
    onSuccess: () => {
      setError(null)
      setStep(2)
    },
    onError: fail,
  })

  const runBaseline = useMutation({
    mutationFn: () => api.baseline(repoId!),
    onSuccess: (outcome) => {
      setBaseline(outcome)
      setError(null)
    },
    onError: fail,
  })

  const addTask = useMutation({
    mutationFn: async () => {
      if (taskMode === 'defined') {
        const { id } = await api.createTask({ repository_id: repoId!, title, prompt })
        return { id, candidates: 0 }
      }
      const res = await api.taskFromCommit({ repository_id: repoId!, sha })
      return { id: res.id, candidates: res.hidden_test_candidates }
    },
    onSuccess: async ({ id, candidates }) => {
      setTaskIds((prev) => [...prev, id])
      setError(null)
      if (candidates > 0) setHidden(await api.hiddenTests(id))
      setTitle('')
      setPrompt('')
      setSha('')
    },
    onError: fail,
  })

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
        config: {
          max_model_requests: budget,
          max_steps: budget,
          timeout_seconds: 1800,
        },
      })
    },
    onSuccess: ({ id }) => navigate(`/experiments/${id}`),
    onError: fail,
  })

  const runs = harnesses.length * models.length * taskIds.length * reps
  const requests = runs * budget
  const overDailyCap = requests > DAILY_FREE_REQUESTS

  const toggle = (list: string[], value: string, set: (v: string[]) => void) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  const codingModels = useMemo(
    () => (availableModels.data ?? []).slice().sort((a, b) => a.model_id.localeCompare(b.model_id)),
    [availableModels.data],
  )

  return (
    <Box>
      <PageTitle
        title="New benchmark run"
        sub="Point it at a repository, choose which harness × model combinations to compare, then watch the matrix execute."
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
        <Panel label="Repository source">
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
          <Typography sx={{ color: C.faint, fontSize: '0.78rem', mb: 2 }}>
            Repositories using git submodules or Git LFS are rejected, and there is a 500&nbsp;MB
            size limit. Analysis detects languages, package managers and test commands — you can
            correct all of them on the next step.
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
      {step === 1 && analysis && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 5 }}>
            <Panel label="Detected">
              <Grid container spacing={2.5}>
                <Grid size={6}>
                  <Stat label="languages" value={analysis.languages.join(', ') || '—'} />
                </Grid>
                <Grid size={6}>
                  <Stat label="package mgr" value={analysis.package_managers.join(', ') || '—'} />
                </Grid>
                <Grid size={6}>
                  <Stat
                    label="size"
                    value={(analysis.size_bytes / 1e6).toFixed(1)}
                    unit="MB"
                  />
                </Grid>
                <Grid size={6}>
                  <Stat
                    label="supported"
                    value={analysis.supported ? 'yes' : 'no'}
                    color={analysis.supported ? C.pass : C.warn}
                  />
                </Grid>
              </Grid>
              {!analysis.supported && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  Language detected but not fully supported. Python and JavaScript/TypeScript have
                  first-class support; others can still run with commands you supply.
                </Alert>
              )}
              {analysis.test_locations.length > 0 && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="overline">test locations</Typography>
                  {analysis.test_locations.slice(0, 6).map((loc) => (
                    <Typography key={loc} sx={{ fontFamily: fonts.mono, fontSize: '0.75rem', color: C.dim }}>
                      {loc}
                    </Typography>
                  ))}
                </Box>
              )}
            </Panel>
          </Grid>
          <Grid size={{ xs: 12, md: 7 }}>
            <Panel label="Commands — edit before continuing">
              {COMMAND_FIELDS.map((field) => (
                <TextField
                  key={field}
                  fullWidth
                  label={field}
                  value={commands[field] ?? ''}
                  onChange={(e) => setCommands({ ...commands, [field]: e.target.value })}
                  sx={{ mb: 1.5 }}
                />
              ))}
              <TextField
                fullWidth
                label="test framework"
                value={framework}
                onChange={(e) => setFramework(e.target.value)}
                helperText="pytest, vitest, jest… decides how test output is parsed into per-case results"
                sx={{ mb: 2 }}
              />
              <Typography sx={{ color: C.faint, fontSize: '0.78rem', mb: 2 }}>
                These are <strong>evaluator-owned</strong>: grading always runs them on a fresh
                snapshot, never inside the agent's workspace, so an agent cannot influence its own
                grade.
              </Typography>
              <Button
                variant="contained"
                onClick={() => saveCommands.mutate()}
                disabled={saveCommands.isPending}
              >
                Save and continue
              </Button>
            </Panel>
          </Grid>
        </Grid>
      )}

      {/* ---------------------------------------------------------------- 3 */}
      {step === 2 && (
        <Panel label="Baseline validation">
          <Typography sx={{ color: C.dim, fontSize: '0.85rem', mb: 2, maxWidth: '70ch' }}>
            Runs your commands on a clean snapshot <em>before</em> any agent touches the repo.
            Failures present at the base commit are recorded so they are never counted as
            regressions the agent introduced.
          </Typography>
          {!baseline && (
            <Button
              variant="contained"
              onClick={() => runBaseline.mutate()}
              disabled={runBaseline.isPending}
              startIcon={runBaseline.isPending ? <CircularProgress size={14} /> : null}
            >
              {runBaseline.isPending ? 'Running baseline…' : 'Run baseline'}
            </Button>
          )}
          {baseline && (
            <>
              <Grid container spacing={3} sx={{ mb: 2 }}>
                <Grid size="auto">
                  <Stat
                    label="benchmarkable"
                    value={baseline.benchmarkable ? 'yes' : 'no'}
                    color={baseline.benchmarkable ? C.pass : C.fail}
                  />
                </Grid>
                {Object.entries(baseline.steps).map(([name, s]) => (
                  <Grid size="auto" key={name}>
                    <Stat
                      label={name}
                      value={s.exit_code === 0 ? 'pass' : `exit ${s.exit_code}`}
                      color={s.exit_code === 0 ? C.pass : C.warn}
                    />
                  </Grid>
                ))}
              </Grid>
              {baseline.warn && (
                <Alert severity="warning" sx={{ mb: 2 }}>
                  Baseline is partially failing. You can proceed — those failures are excluded from
                  regression counting.
                </Alert>
              )}
              {!baseline.benchmarkable && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  Baseline could not establish a signal (install/build failed, or tests could not be
                  collected). Fix the commands on the previous step before benchmarking.
                </Alert>
              )}
              <Button variant="contained" disabled={!baseline.benchmarkable} onClick={() => setStep(3)}>
                Continue
              </Button>
            </>
          )}
        </Panel>
      )}

      {/* ---------------------------------------------------------------- 4 */}
      {step === 3 && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Panel label="Add a task">
              <ToggleButtonGroup
                exclusive
                size="small"
                value={taskMode}
                onChange={(_, v) => v && setTaskMode(v)}
                sx={{ mb: 2 }}
              >
                <ToggleButton value="defined">Describe it</ToggleButton>
                <ToggleButton value="commit">Replay a commit</ToggleButton>
              </ToggleButtonGroup>

              {taskMode === 'defined' ? (
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
                    disabled={!title.trim() || !prompt.trim() || addTask.isPending}
                    onClick={() => addTask.mutate()}
                  >
                    Add task
                  </Button>
                </>
              ) : (
                <>
                  <Typography sx={{ color: C.dim, fontSize: '0.82rem', mb: 2, maxWidth: '68ch' }}>
                    The commit's <strong>parent</strong> becomes the starting state and the commit
                    itself is the known solution. The agent only ever sees a fresh snapshot at the
                    parent — no remotes, no future history, no solution commit.
                  </Typography>
                  <TextField
                    fullWidth
                    select
                    label="commit"
                    value={sha}
                    onChange={(e) => setSha(e.target.value)}
                    sx={{ mb: 2 }}
                    disabled={commits.isLoading}
                  >
                    {(commits.data ?? [])
                      .filter((c: Commit) => c.parent)
                      .slice(0, 60)
                      .map((c: Commit) => (
                        <MenuItem key={c.sha} value={c.sha} sx={{ fontFamily: fonts.mono, fontSize: '0.78rem' }}>
                          {c.sha.slice(0, 8)} — {c.subject.slice(0, 68)}
                        </MenuItem>
                      ))}
                  </TextField>
                  <Button
                    variant="outlined"
                    disabled={!sha || addTask.isPending}
                    onClick={() => addTask.mutate()}
                  >
                    Add from commit
                  </Button>
                </>
              )}

              <Divider sx={{ my: 2.5 }} />
              <Typography variant="overline">selected · {taskIds.length}</Typography>
              {taskIds.length === 0 ? (
                <Empty>No tasks yet. Add between one and five.</Empty>
              ) : (
                taskIds.map((id, i) => (
                  <Typography key={id} sx={{ fontFamily: fonts.mono, fontSize: '0.78rem', color: C.dim }}>
                    {i + 1}. {id.slice(0, 12)}
                  </Typography>
                ))
              )}
              <Box sx={{ mt: 2 }}>
                <Button variant="contained" disabled={taskIds.length === 0} onClick={() => setStep(4)}>
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
                <Empty>None extracted. Replay a commit that adds tests to see candidates.</Empty>
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
                    <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.68rem', color: C.faint, pl: 4 }}>
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

      {/* ---------------------------------------------------------------- 5 */}
      {step === 4 && (
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
                      <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.65rem', color: C.faint }}>
                        {h.sandboxed ? 'sandboxed' : 'in-process'}
                      </Typography>
                    </Box>
                  }
                  sx={{ display: 'flex', mb: 0.5 }}
                />
              ))}
            </Panel>

            <Panel label="Models">
              {availableModels.isLoading && <CircularProgress size={16} />}
              {availableModels.isError && (
                <Alert severity="warning">
                  Could not list models — check OPENROUTER_API_KEY in .env.
                </Alert>
              )}
              <Box sx={{ maxHeight: 320, overflowY: 'auto' }}>
                {codingModels.map((m) => (
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
                        <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.64rem', color: C.faint }}>
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
                      <TableCell sx={{ border: 0, py: 0.4, pl: 0, color: C.faint, fontFamily: fonts.mono, fontSize: '0.72rem' }}>
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
                  limit are parked as rate-limited and resume automatically, so the matrix will
                  simply take longer rather than fail.
                </Alert>
              )}
            </Panel>

            <Button
              fullWidth
              size="large"
              variant="contained"
              disabled={runs === 0 || launch.isPending}
              onClick={() => launch.mutate()}
              startIcon={launch.isPending ? <CircularProgress size={14} /> : null}
            >
              {launch.isPending ? 'Starting…' : `Start ${runs} run${runs === 1 ? '' : 's'}`}
            </Button>
          </Grid>
        </Grid>
      )}
    </Box>
  )
}
