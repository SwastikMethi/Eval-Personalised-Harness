import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Grid,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { Empty, Mono, PageTitle, Panel, Stat, StateChip } from '../components/primitives'
import { C, fonts } from '../theme'

function Diff({ patch }: { patch: string }) {
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 2,
        overflowX: 'auto',
        backgroundColor: C.bg,
        border: `1px solid ${C.lineSoft}`,
        fontFamily: fonts.mono,
        fontSize: '0.74rem',
        lineHeight: 1.6,
        maxHeight: 460,
      }}
    >
      {patch.split('\n').map((line, i) => {
        const color = line.startsWith('+++') || line.startsWith('---')
          ? C.dim
          : line.startsWith('+')
            ? C.pass
            : line.startsWith('-')
              ? C.fail
              : line.startsWith('@@')
                ? C.live
                : C.dim
        return (
          <Box key={i} component="span" sx={{ color, display: 'block', whiteSpace: 'pre' }}>
            {line || ' '}
          </Box>
        )
      })}
    </Box>
  )
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>()
  const detail = useQuery({
    queryKey: ['run', id],
    queryFn: () => api.runDetail(id!),
    enabled: Boolean(id),
    refetchInterval: (q) =>
      ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'].includes(q.state.data?.state ?? '')
        ? false
        : 3000,
  })
  const patch = useQuery({
    queryKey: ['patch', id],
    queryFn: () => api.runPatch(id!),
    enabled: Boolean(detail.data?.has_patch),
  })

  if (detail.isLoading) return <CircularProgress size={20} />
  if (detail.isError || !detail.data)
    return <Alert severity="error">Run not found.</Alert>

  const d = detail.data
  const usage = d.usage ?? {}
  const ev = d.evaluation
  const results = ev?.results ?? {}

  return (
    <Box>
      <PageTitle
        title={`${d.harness ?? 'run'} · ${(d.model_id ?? '').replace(/:free$/, '')}`}
        sub={d.task?.title}
        action={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <StateChip state={d.state} size="medium" />
            {['FAILED', 'TIMED_OUT'].includes(d.state) && (
              <Button size="small" variant="outlined" onClick={() => api.retryRun(d.id)}>
                Retry
              </Button>
            )}
          </Box>
        }
      />

      {d.error_message && (
        <Alert severity={d.state === 'FAILED' ? 'error' : 'warning'} sx={{ mb: 3 }}>
          <Mono size="0.74rem" color="inherit">
            [{d.error_category}] {d.error_message.slice(0, 600)}
          </Mono>
        </Alert>
      )}

      <Panel sx={{ mb: 3 }}>
        <Grid container spacing={3}>
          <Grid size="auto">
            <Stat label="repetition" value={d.repetition} />
          </Grid>
          <Grid size="auto">
            <Stat label="model requests" value={String(usage.requests ?? '—')} />
          </Grid>
          <Grid size="auto">
            <Stat label="input tokens" value={Number(usage.input_tokens ?? 0).toLocaleString()} />
          </Grid>
          <Grid size="auto">
            <Stat label="output tokens" value={Number(usage.output_tokens ?? 0).toLocaleString()} />
          </Grid>
          <Grid size="auto">
            <Stat
              label="cost"
              value={`$${Number(usage.cost_usd ?? 0).toFixed(4)}`}
              hint="free models record $0"
            />
          </Grid>
          <Grid size="auto">
            <Stat
              label="score"
              value={ev?.score === null || ev?.score === undefined ? '—' : ev.score.toFixed(2)}
              color={ev?.score ? C.pass : C.faint}
            />
          </Grid>
          {usage.rate_limited ? (
            <Grid size="auto">
              <Stat label="throttled" value="yes" color={C.warn} />
            </Grid>
          ) : null}
          {usage.budget_exhausted ? (
            <Grid size="auto">
              <Stat label="budget" value="exhausted" color={C.warn} />
            </Grid>
          ) : null}
        </Grid>
      </Panel>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Panel label="Patch" sx={{ mb: 2 }}>
            {!d.has_patch ? (
              <Empty>
                No patch produced. That is a legitimate benchmark result — it scores zero rather
                than being treated as an error.
              </Empty>
            ) : patch.isLoading ? (
              <CircularProgress size={16} />
            ) : patch.data ? (
              <Diff patch={patch.data.patch} />
            ) : (
              <Empty>Patch artifact missing from disk.</Empty>
            )}
          </Panel>

          <Panel label="Evaluation">
            {!ev ? (
              <Empty>Not evaluated.</Empty>
            ) : (
              <>
                <Box sx={{ display: 'flex', gap: 3, mb: 2 }}>
                  <Stat
                    label="signal"
                    value={ev.signal}
                    color={ev.signal === 'ok' ? C.pass : C.warn}
                  />
                </Box>
                {Object.entries(results).map(([name, value]) => (
                  <Box
                    key={name}
                    sx={{ py: 0.7, borderBottom: `1px solid ${C.lineSoft}` }}
                  >
                    <Mono size="0.74rem" color={C.text}>
                      {name}
                    </Mono>
                    <Typography
                      sx={{
                        fontFamily: fonts.mono,
                        fontSize: '0.7rem',
                        color: C.dim,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}
                    >
                      {JSON.stringify(value)}
                    </Typography>
                  </Box>
                ))}
              </>
            )}
          </Panel>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          <Panel label="Timeline" sx={{ mb: 2 }}>
            {d.timeline.length === 0 ? (
              <Empty>No events.</Empty>
            ) : (
              d.timeline.map((e, i) => (
                <Box key={i} sx={{ display: 'flex', gap: 1.5, py: 0.6 }}>
                  <Mono size="0.66rem" color={C.faint}>
                    {e.at.slice(11, 19)}
                  </Mono>
                  <Mono size="0.74rem" color={C.text}>
                    {e.type}
                  </Mono>
                </Box>
              ))
            )}
          </Panel>

          <Panel label="Model requests">
            {d.model_requests.length === 0 ? (
              <Empty>The agent never called the model.</Empty>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>status</TableCell>
                    <TableCell align="right">latency</TableCell>
                    <TableCell align="right">in</TableCell>
                    <TableCell align="right">out</TableCell>
                    <TableCell>provider</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {d.model_requests.map((m, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <Mono color={m.http_status === 200 ? C.pass : C.warn}>{m.http_status}</Mono>
                      </TableCell>
                      <TableCell align="right">
                        <Mono>{m.latency_ms}ms</Mono>
                      </TableCell>
                      <TableCell align="right">
                        <Mono>{m.input_tokens ?? '—'}</Mono>
                      </TableCell>
                      <TableCell align="right">
                        <Mono>{m.output_tokens ?? '—'}</Mono>
                      </TableCell>
                      <TableCell>
                        <Mono size="0.7rem">{m.routed_provider ?? '—'}</Mono>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Panel>
        </Grid>
      </Grid>
    </Box>
  )
}
