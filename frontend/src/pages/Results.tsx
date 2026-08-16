import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Grid,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip as MuiTooltip,
  Typography,
} from '@mui/material'
import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import type { CombinationStats, ComboRecommendation } from '../api'
import { Empty, Mono, Panel, Stat } from '../components/primitives'
import { C, fonts } from '../theme'

const CARDS: { key: string; label: string; blurb: string }[] = [
  { key: 'best_quality', label: 'Best quality', blurb: 'highest correctness' },
  { key: 'best_reliability', label: 'Best reliability', blurb: 'most consistent across repetitions' },
  { key: 'best_efficiency', label: 'Best efficiency', blurb: 'least time and tokens, correctness-gated' },
  { key: 'best_balanced', label: 'Best balanced', blurb: 'weighted across all dimensions' },
]

function RecommendationCard({
  label,
  blurb,
  rec,
}: {
  label: string
  blurb: string
  rec: ComboRecommendation | undefined
}) {
  if (!rec) {
    return (
      <Panel label={label} sx={{ height: '100%' }}>
        <Empty>No eligible combination.</Empty>
        <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.66rem', color: C.faint, mt: 1 }}>
          {blurb}
        </Typography>
      </Panel>
    )
  }
  // A tie is a result, and printing a name here would overstate it — the card
  // is the most-read thing on the page, so it must not claim a winner the
  // numbers do not support.
  if (rec.tied) {
    return (
      <Panel label={label} sx={{ height: '100%' }}>
        <Typography
          sx={{ fontFamily: fonts.mono, fontSize: '0.9rem', color: C.warn, fontWeight: 600 }}
        >
          no winner
        </Typography>
        <Typography sx={{ fontSize: '0.76rem', color: C.dim, mt: 1 }}>{rec.why}</Typography>
        <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.66rem', color: C.faint, mt: 1.5 }}>
          {blurb}
        </Typography>
      </Panel>
    )
  }
  return (
    <Panel
      label={label}
      sx={{
        height: '100%',
        borderColor: C.line,
        position: 'relative',
        overflow: 'hidden',
        '&::before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(160deg, ${C.live}0A, transparent 55%)`,
          pointerEvents: 'none',
        },
      }}
    >
      <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.9rem', color: C.text, fontWeight: 600 }}>
        {rec.harness}
      </Typography>
      <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.74rem', color: C.dim, mb: 1.5 }}>
        {rec.model_id}
      </Typography>
      <Grid container spacing={1.5}>
        <Grid size={6}>
          <Stat label="correctness" value={rec.correctness.toFixed(2)} color={C.pass} />
        </Grid>
        <Grid size={6}>
          <Stat label="reliability" value={rec.reliability.toFixed(2)} />
        </Grid>
        <Grid size={6}>
          <Stat label="avg time" value={rec.avg_duration_s ? rec.avg_duration_s.toFixed(0) : '—'} unit="s" />
        </Grid>
        <Grid size={6}>
          <Stat
            label="avg tokens"
            value={rec.avg_tokens ? Math.round(rec.avg_tokens).toLocaleString() : '—'}
          />
        </Grid>
      </Grid>
      {rec.why && (
        <Typography sx={{ fontSize: '0.78rem', color: C.dim, mt: 1.5 }}>{rec.why}</Typography>
      )}
      <Box sx={{ display: 'flex', gap: 0.5, mt: 1.5, flexWrap: 'wrap' }}>
        <Chip
          size="small"
          variant="outlined"
          label={`${rec.completed_reps} reps`}
          sx={{ color: C.dim }}
        />
        {rec.statistically_weak && (
          <MuiTooltip title="Fewer than 3 completed repetitions — no significance is claimed">
            <Chip
              size="small"
              variant="outlined"
              label="statistically weak"
              sx={{ color: C.warn, borderColor: `${C.warn}55` }}
            />
          </MuiTooltip>
        )}
      </Box>
    </Panel>
  )
}

function ParetoChart({
  title,
  xLabel,
  data,
  frontier,
}: {
  title: string
  xLabel: string
  data: { id: string; label: string; x: number; y: number }[]
  frontier: string[]
}) {
  if (data.length === 0) {
    return (
      <Panel label={title}>
        <Empty>No eligible combinations to plot yet.</Empty>
      </Panel>
    )
  }
  return (
    <Panel label={title}>
      <ResponsiveContainer width="100%" height={230}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke={C.lineSoft} />
          <XAxis
            type="number"
            dataKey="x"
            name={xLabel}
            tick={{ fill: C.faint, fontSize: 10, fontFamily: fonts.mono }}
            stroke={C.line}
            label={{ value: xLabel, position: 'insideBottom', offset: -10, fill: C.faint, fontSize: 10 }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="correctness"
            domain={[0, 1]}
            tick={{ fill: C.faint, fontSize: 10, fontFamily: fonts.mono }}
            stroke={C.line}
          />
          <Tooltip
            cursor={{ stroke: C.line }}
            contentStyle={{
              background: C.surfaceHi,
              border: `1px solid ${C.line}`,
              fontFamily: fonts.mono,
              fontSize: 12,
            }}
            labelFormatter={() => ''}
          />
          <Scatter data={data}>
            {data.map((d) => (
              // On the frontier = not dominated on both axes. Filled and cyan;
              // everything else stays muted so the frontier reads instantly.
              <Cell
                key={d.id}
                fill={frontier.includes(d.id) ? C.live : 'transparent'}
                stroke={frontier.includes(d.id) ? C.live : C.faint}
                r={6}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.64rem', color: C.faint, mt: 0.5 }}>
        filled = on the Pareto frontier (nothing beats it on both axes)
      </Typography>
    </Panel>
  )
}

export default function Results({ experimentId }: { experimentId: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['results', experimentId],
    queryFn: () => api.results(experimentId),
    refetchInterval: 10_000,
  })
  // On demand, not on load: it costs a model call and would be worded
  // differently every time the page refreshed.
  const summary = useMutation({ mutationFn: () => api.summary(experimentId) })

  if (isLoading) return <CircularProgress size={20} />
  if (isError)
    return <Alert severity="error">{error instanceof Error ? error.message : 'failed'}</Alert>
  if (!data || data.combinations.length === 0)
    return (
      <Panel>
        <Empty>No results yet — they appear as runs reach a terminal state.</Empty>
      </Panel>
    )

  const label = (c: CombinationStats) => `${c.harness} · ${c.model_id.replace(/:free$/, '')}`
  const eligible = data.combinations.filter((c) => c.eligible)
  const tokenPoints = eligible
    .filter((c) => c.mean_tokens)
    .map((c) => ({ id: c.combination_id, label: label(c), x: c.mean_tokens!, y: c.mean_score ?? 0 }))
  const durationPoints = eligible
    .filter((c) => c.mean_duration_s)
    .map((c) => ({
      id: c.combination_id,
      label: label(c),
      x: c.mean_duration_s!,
      y: c.mean_score ?? 0,
    }))

  const failureBuckets = data.combinations.reduce<Record<string, number>>((acc, c) => {
    for (const reason of c.ineligible_reasons) acc[reason] = (acc[reason] ?? 0) + 1
    return acc
  }, {})

  return (
    <Box>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {CARDS.map((card) => (
          <Grid size={{ xs: 12, sm: 6, lg: 3 }} key={card.key}>
            <RecommendationCard
              label={card.label}
              blurb={card.blurb}
              rec={data.recommendations[card.key]}
            />
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <ParetoChart
            title="Correctness vs tokens"
            xLabel="mean tokens"
            data={tokenPoints}
            frontier={data.pareto.correctness_vs_tokens ?? []}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <ParetoChart
            title="Correctness vs duration"
            xLabel="mean seconds"
            data={durationPoints}
            frontier={data.pareto.correctness_vs_duration ?? []}
          />
        </Grid>
      </Grid>

      <Panel label="Every combination" sx={{ mb: 3 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>harness</TableCell>
              <TableCell>model</TableCell>
              <TableCell align="right">runs</TableCell>
              <TableCell align="right">success</TableCell>
              <TableCell align="right">score</TableCell>
              <TableCell align="right">σ</TableCell>
              <TableCell align="right">empty patch</TableCell>
              <TableCell align="right">tokens</TableCell>
              <TableCell align="right">time</TableCell>
              <TableCell align="right">weighted</TableCell>
              <TableCell>status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.combinations
              .slice()
              .sort((a, b) => (b.weighted_score ?? -1) - (a.weighted_score ?? -1))
              .map((c) => (
                <TableRow key={c.combination_id} hover>
                  <TableCell>
                    <Mono color={C.text}>{c.harness}</Mono>
                  </TableCell>
                  <TableCell>
                    <Mono size="0.74rem">{c.model_id.replace(/:free$/, '')}</Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono>
                      {c.completed}/{c.runs}
                    </Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono color={c.success_rate === 1 ? C.pass : undefined}>
                      {(c.success_rate * 100).toFixed(0)}%
                    </Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono color={c.mean_score ? C.pass : undefined}>
                      {c.mean_score === null ? '—' : c.mean_score.toFixed(2)}
                    </Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono>{c.stdev_score === null ? '—' : c.stdev_score.toFixed(2)}</Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono color={c.empty_patch_rate > 0 ? C.warn : undefined}>
                      {(c.empty_patch_rate * 100).toFixed(0)}%
                    </Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono>{c.mean_tokens ? Math.round(c.mean_tokens).toLocaleString() : '—'}</Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono>{c.mean_duration_s ? `${c.mean_duration_s.toFixed(0)}s` : '—'}</Mono>
                  </TableCell>
                  <TableCell align="right">
                    <Mono color={C.text}>
                      {c.weighted_score === null ? '—' : c.weighted_score.toFixed(3)}
                    </Mono>
                  </TableCell>
                  <TableCell>
                    {c.eligible ? (
                      <Chip size="small" variant="outlined" label="eligible" sx={{ color: C.pass, borderColor: `${C.pass}55` }} />
                    ) : (
                      <MuiTooltip title={c.ineligible_reasons.join(' · ')}>
                        <Chip
                          size="small"
                          variant="outlined"
                          label="excluded"
                          sx={{ color: C.warn, borderColor: `${C.warn}55` }}
                        />
                      </MuiTooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </Panel>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Panel label="Why combinations were excluded">
            {Object.keys(failureBuckets).length === 0 ? (
              <Empty>Nothing excluded — every combination produced a usable signal.</Empty>
            ) : (
              Object.entries(failureBuckets)
                .sort((a, b) => b[1] - a[1])
                .map(([reason, n]) => (
                  <Box
                    key={reason}
                    sx={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      py: 0.7,
                      borderBottom: `1px solid ${C.lineSoft}`,
                    }}
                  >
                    <Mono size="0.76rem">{reason}</Mono>
                    <Mono color={C.warn}>{n}</Mono>
                  </Box>
                ))
            )}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12 }}>
          <Panel
            label="Which combination did better"
            action={
              <Button
                size="small"
                variant="outlined"
                disabled={summary.isPending}
                onClick={() => summary.mutate()}
                startIcon={summary.isPending ? <CircularProgress size={12} /> : null}
              >
                {summary.isPending ? 'Reading the results…' : 'Write the comparison'}
              </Button>
            }
          >
            {summary.isError && (
              <Alert severity="error" sx={{ mb: 1.5 }}>
                {(summary.error as Error).message}
              </Alert>
            )}
            {summary.data?.summary ? (
              <>
                <Typography
                  sx={{ fontSize: '0.86rem', color: C.text, whiteSpace: 'pre-wrap', mb: 1 }}
                >
                  {summary.data.summary}
                </Typography>
                <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.66rem', color: C.faint }}>
                  written by {summary.data.provenance?.model} — reads only the numbers below
                </Typography>
              </>
            ) : (
              <Empty>
                Not generated yet. It costs one model call, so it is not written automatically.
              </Empty>
            )}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Panel label="Read this before trusting the numbers">
            {(data.caveats ?? []).map((caveat) => (
              <Typography
                key={caveat}
                sx={{ fontSize: '0.8rem', color: C.dim, mb: 1, display: 'flex', gap: 1 }}
              >
                <Box component="span" sx={{ color: C.warn }}>
                  —
                </Box>
                {caveat}
              </Typography>
            ))}
          </Panel>
        </Grid>
      </Grid>
    </Box>
  )
}
