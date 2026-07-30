import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Container,
  Grid,
  LinearProgress,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import {
  CartesianGrid,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from 'recharts'
import { api, type ComboRecommendation } from '../api'

const CARD_LABELS: Record<string, string> = {
  best_quality: 'Best quality',
  best_reliability: 'Best reliability',
  best_efficiency: 'Best efficiency',
  best_balanced: 'Best balanced',
}

function RecommendationCard({ label, rec }: { label: string; rec: ComboRecommendation }) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="overline">{label}</Typography>
        <Typography variant="h6">
          {rec.harness} × {rec.model_id}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          correctness {(rec.correctness * 100).toFixed(0)}% · reliability{' '}
          {(rec.reliability * 100).toFixed(0)}% · balanced {(rec.balanced * 100).toFixed(0)}%
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {rec.tasks} task(s), {rec.completed_reps} completed reps
          {rec.avg_tokens != null && ` · ~${Math.round(rec.avg_tokens)} tokens`}
        </Typography>
        {rec.why && <Typography variant="caption">{rec.why}</Typography>}
        {rec.statistically_weak && (
          <Chip label="statistically weak" color="warning" size="small" sx={{ mt: 1 }} />
        )}
      </CardContent>
    </Card>
  )
}

export default function ExperimentDetail() {
  const { id = '' } = useParams()
  const status = useQuery({
    queryKey: ['experiment', id],
    queryFn: () => api.experiment(id),
    refetchInterval: (query) => {
      const byState = query.state.data?.runs.by_state ?? {}
      const total = query.state.data?.runs.total ?? 0
      const done =
        (byState.COMPLETED ?? 0) +
        (byState.FAILED ?? 0) +
        (byState.CANCELLED ?? 0) +
        (byState.TIMED_OUT ?? 0)
      return total > 0 && done === total ? false : 1500
    },
  })
  const results = useQuery({
    queryKey: ['results', id],
    queryFn: () => api.results(id),
    enabled: status.isSuccess,
    refetchInterval: 3000,
  })

  if (status.isError) return <Alert severity="error">Experiment not found.</Alert>
  const byState = status.data?.runs.by_state ?? {}
  const total = status.data?.runs.total ?? 0
  const completed = byState.COMPLETED ?? 0
  const recs = results.data?.recommendations ?? {}
  const combos = results.data?.combinations ?? []
  const scatter = combos
    .filter((c) => c.eligible)
    .map((c) => ({
      name: `${c.harness}`,
      tokens: c.mean_tokens ?? 0,
      correctness: (c.mean_score ?? 0) * 100,
    }))

  return (
    <Container sx={{ mt: 4 }}>
      <Typography variant="h5" gutterBottom>
        {status.data?.name ?? 'Experiment'}{' '}
        <Chip label={status.data?.status ?? '…'} size="small" />
      </Typography>
      <Box sx={{ mb: 3 }}>
        <Typography variant="body2" color="text.secondary">
          {completed}/{total} runs completed{' '}
          {Object.entries(byState)
            .map(([s, n]) => `${s}: ${n}`)
            .join(' · ')}
        </Typography>
        <LinearProgress
          variant="determinate"
          value={total ? (completed / total) * 100 : 0}
          sx={{ mt: 1 }}
        />
      </Box>

      {Object.keys(recs).length > 0 && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          {Object.entries(CARD_LABELS).map(
            ([key, label]) =>
              recs[key] && (
                <Grid key={key} size={{ xs: 12, sm: 6, md: 3 }}>
                  <RecommendationCard label={label} rec={recs[key]} />
                </Grid>
              ),
          )}
        </Grid>
      )}

      {combos.length > 0 && (
        <>
          <Typography variant="h6" gutterBottom>
            Combinations
          </Typography>
          <Table size="small" sx={{ mb: 3 }}>
            <TableHead>
              <TableRow>
                <TableCell>Harness</TableCell>
                <TableCell>Model</TableCell>
                <TableCell align="right">Runs</TableCell>
                <TableCell align="right">Score</TableCell>
                <TableCell align="right">Success</TableCell>
                <TableCell align="right">Weighted</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {combos.map((c) => (
                <TableRow key={c.combination_id}>
                  <TableCell>{c.harness}</TableCell>
                  <TableCell>{c.model_id}</TableCell>
                  <TableCell align="right">
                    {c.completed}/{c.runs}
                  </TableCell>
                  <TableCell align="right">
                    {c.mean_score != null ? (c.mean_score * 100).toFixed(0) + '%' : '—'}
                  </TableCell>
                  <TableCell align="right">{(c.success_rate * 100).toFixed(0)}%</TableCell>
                  <TableCell align="right">
                    {c.weighted_score != null ? (c.weighted_score * 100).toFixed(0) + '%' : '—'}
                  </TableCell>
                  <TableCell>
                    {c.eligible ? (
                      <Chip label="eligible" color="success" size="small" />
                    ) : (
                      <Chip
                        label={c.ineligible_reasons[0] ?? 'ineligible'}
                        color="error"
                        size="small"
                      />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {scatter.length > 0 && (
            <>
              <Typography variant="h6" gutterBottom>
                Correctness vs tokens
              </Typography>
              <ResponsiveContainer width="100%" height={280}>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="tokens" name="tokens" type="number" />
                  <YAxis dataKey="correctness" name="correctness %" unit="%" domain={[0, 100]} />
                  <Tooltip cursor={{ strokeDasharray: '3 3' }} />
                  <Scatter data={scatter} fill="#37474f" />
                </ScatterChart>
              </ResponsiveContainer>
            </>
          )}
        </>
      )}
      {results.data?.caveats?.map((c) => (
        <Typography key={c} variant="caption" sx={{ display: 'block' }} color="text.secondary">
          ⚠ {c}
        </Typography>
      ))}
      <Box sx={{ mt: 2 }}>
        <Link to="/">← Dashboard</Link>
      </Box>
    </Container>
  )
}
