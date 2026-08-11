import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Grid,
  LinearProgress,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Empty, Mono, PageTitle, Panel, Stat, StateChip } from '../components/primitives'
import { C, fonts } from '../theme'
import { useExperimentStream } from '../useExperimentStream'
import Results from './Results'

const fmtSeconds = (s: number | null | undefined) =>
  s === null || s === undefined ? '—' : s < 60 ? `${s.toFixed(0)}s` : `${(s / 60).toFixed(1)}m`

export default function Experiment() {
  const { id } = useParams<{ id: string }>()
  const [tab, setTab] = useState(0)
  const { progress, events, connected, finished } = useExperimentStream(id)

  const meta = useQuery({
    queryKey: ['experiment', id],
    queryFn: () => api.experiment(id!),
    enabled: Boolean(id),
  })
  // A fallback poll so the page is still correct if EventSource is unavailable.
  const polled = useQuery({
    queryKey: ['progress', id],
    queryFn: () => api.progress(id!),
    enabled: Boolean(id) && !connected && !finished,
    refetchInterval: 3000,
  })

  const state = progress ?? polled.data ?? null
  const pct = state && state.total ? (state.done / state.total) * 100 : 0
  const active = state?.runs.filter((r) =>
    ['RUNNING', 'PREPARING', 'EVALUATING'].includes(r.state),
  ) ?? []
  const throttled = state?.runs.filter((r) => r.rate_limited || r.state === 'RATE_LIMITED') ?? []
  const totalRequests = state?.runs.reduce((n, r) => n + (r.model_requests ?? 0), 0) ?? 0
  const totalTokens =
    state?.runs.reduce((n, r) => n + (r.input_tokens ?? 0) + (r.output_tokens ?? 0), 0) ?? 0

  return (
    <Box>
      <PageTitle
        title={meta.data?.name ?? 'Experiment'}
        sub={
          state?.finished
            ? 'Finished. The comparison below ranks every combination that produced a usable signal.'
            : 'Executing. Each row is one repetition of one harness × model pair.'
        }
        action={
          <Box sx={{ display: 'flex', gap: 1 }}>
            {!state?.finished && (
              <>
                <Button variant="outlined" size="small" onClick={() => api.pause(id!)}>
                  Pause
                </Button>
                <Button variant="outlined" size="small" onClick={() => api.resume(id!)}>
                  Resume
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  color="error"
                  onClick={() => api.cancelExperiment(id!)}
                >
                  Cancel
                </Button>
              </>
            )}
          </Box>
        }
      />

      <Panel sx={{ mb: 3, p: 0, overflow: 'hidden' }}>
        <Box sx={{ p: 2.5, pb: 2 }}>
          <Grid container spacing={3} sx={{ alignItems: 'flex-start' }}>
            <Grid size="auto">
              <Stat
                label="progress"
                value={`${state?.done ?? 0}/${state?.total ?? 0}`}
                color={state?.finished ? C.pass : C.live}
              />
            </Grid>
            <Grid size="auto">
              <Stat label="active" value={active.length} color={active.length ? C.live : C.faint} />
            </Grid>
            <Grid size="auto">
              <Stat
                label="throttled"
                value={throttled.length}
                color={throttled.length ? C.warn : C.faint}
              />
            </Grid>
            <Grid size="auto">
              <Stat label="model requests" value={totalRequests} />
            </Grid>
            <Grid size="auto">
              <Stat label="tokens" value={totalTokens.toLocaleString()} />
            </Grid>
            <Grid size="auto" sx={{ ml: 'auto' }}>
              <Stat
                label="stream"
                value={connected ? 'live' : finished ? 'closed' : 'polling'}
                color={connected ? C.live : C.faint}
              />
            </Grid>
          </Grid>
        </Box>
        <LinearProgress
          variant="determinate"
          value={pct}
          sx={{
            '& .MuiLinearProgress-bar': {
              backgroundColor: state?.finished ? C.pass : C.live,
              transition: 'transform 600ms ease',
            },
          }}
        />
      </Panel>

      {throttled.length > 0 && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          {throttled.length} run{throttled.length === 1 ? '' : 's'} hit provider rate limits. They
          are parked and resume automatically with backoff — nothing is lost, the matrix just takes
          longer.
        </Alert>
      )}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: `1px solid ${C.line}` }}>
        <Tab label="Live" />
        <Tab label="Comparison" />
      </Tabs>

      {tab === 0 && (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 8 }}>
            <Panel label="Runs">
              {!state || state.runs.length === 0 ? (
                <Empty>No runs queued yet.</Empty>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>harness</TableCell>
                      <TableCell>model</TableCell>
                      <TableCell align="right">rep</TableCell>
                      <TableCell>state</TableCell>
                      <TableCell align="right">elapsed</TableCell>
                      <TableCell align="right">req</TableCell>
                      <TableCell align="right">tokens</TableCell>
                      <TableCell align="right">score</TableCell>
                      <TableCell />
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {state.runs.map((r) => (
                      <TableRow key={r.run_id} hover>
                        <TableCell>
                          <Mono color={C.text}>{r.harness}</Mono>
                        </TableCell>
                        <TableCell>
                          <Tooltip title={r.model_id}>
                            <Box component="span">
                              <Mono size="0.74rem">{r.model_id.replace(/:free$/, '')}</Mono>
                            </Box>
                          </Tooltip>
                        </TableCell>
                        <TableCell align="right">
                          <Mono>{r.repetition}</Mono>
                        </TableCell>
                        <TableCell>
                          <StateChip state={r.state} />
                          {r.budget_exhausted && (
                            <Tooltip title="Used its entire model-request budget">
                              <Box component="span" sx={{ ml: 0.5 }}>
                                <Mono size="0.62rem" color={C.warn}>
                                  budget
                                </Mono>
                              </Box>
                            </Tooltip>
                          )}
                        </TableCell>
                        <TableCell align="right">
                          <Mono>{fmtSeconds(r.elapsed_s)}</Mono>
                        </TableCell>
                        <TableCell align="right">
                          <Mono>{r.model_requests ?? '—'}</Mono>
                        </TableCell>
                        <TableCell align="right">
                          <Mono>
                            {r.input_tokens || r.output_tokens
                              ? ((r.input_tokens ?? 0) + (r.output_tokens ?? 0)).toLocaleString()
                              : '—'}
                          </Mono>
                        </TableCell>
                        <TableCell align="right">
                          <Mono color={r.score ? C.pass : undefined}>
                            {r.score === null || r.score === undefined ? '—' : r.score.toFixed(2)}
                          </Mono>
                        </TableCell>
                        <TableCell align="right">
                          <Typography
                            component={Link}
                            to={`/runs/${r.run_id}`}
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: '0.7rem',
                              color: C.live,
                              textDecoration: 'none',
                              '&:hover': { textDecoration: 'underline' },
                            }}
                          >
                            detail
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Panel>
          </Grid>

          <Grid size={{ xs: 12, lg: 4 }}>
            <Panel label="Activity">
              {events.length === 0 ? (
                <Empty>Waiting for the first event…</Empty>
              ) : (
                <Box sx={{ maxHeight: 520, overflowY: 'auto' }}>
                  {events.map((e, i) => (
                    <Box
                      key={`${e.run_id}-${e.at}-${i}`}
                      sx={{
                        display: 'flex',
                        gap: 1,
                        py: 0.6,
                        borderBottom: `1px solid ${C.lineSoft}`,
                        animation: i === 0 ? 'asoRise 300ms ease both' : undefined,
                      }}
                    >
                      <Mono size="0.66rem" color={C.faint}>
                        {e.at.slice(11, 19)}
                      </Mono>
                      <Mono size="0.72rem" color={C.text}>
                        {e.type}
                      </Mono>
                      <Box sx={{ flexGrow: 1 }} />
                      <Mono size="0.66rem" color={C.faint}>
                        {e.run_id.slice(0, 6)}
                      </Mono>
                    </Box>
                  ))}
                </Box>
              )}
            </Panel>
          </Grid>
        </Grid>
      )}

      {tab === 1 && <Results experimentId={id!} />}
    </Box>
  )
}
