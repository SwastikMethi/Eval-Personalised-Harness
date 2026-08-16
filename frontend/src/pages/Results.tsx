import { useMutation, useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
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
import { color, radius, space } from '../design/tokens'
import { respectMotion, rise, stagger } from '../design/motion'
import { font, type } from '../design/typography'
import { Button, Empty, Grid, Metric, Notice, Panel, ScrollX, Status } from '../ui'

const CARDS: { key: string; label: string; blurb: string }[] = [
  { key: 'best_quality', label: 'Best quality', blurb: 'highest correctness' },
  {
    key: 'best_reliability',
    label: 'Best reliability',
    blurb: 'most consistent across repetitions',
  },
  {
    key: 'best_efficiency',
    label: 'Best efficiency',
    blurb: 'least time and tokens, correctness-gated',
  },
  { key: 'best_balanced', label: 'Best balanced', blurb: 'weighted across all dimensions' },
]

function Blurb({ children }: { children: string }) {
  return (
    <div style={{ ...type.caption, color: color.faint, marginTop: space[3] }}>{children}</div>
  )
}

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
      <Panel label={label} style={{ height: '100%', marginBottom: 0 }}>
        <Empty>No eligible combination.</Empty>
        <Blurb>{blurb}</Blurb>
      </Panel>
    )
  }

  // A tie is a result, and printing a name here would overstate it — the card
  // is the most-read thing on the page, so it must not claim a winner the
  // numbers do not support.
  if (rec.tied) {
    return (
      <Panel label={label} style={{ height: '100%', marginBottom: 0 }}>
        <div style={{ fontFamily: font.mono, fontSize: 15, color: color.warn, fontWeight: 600 }}>
          no winner
        </div>
        <p style={{ ...type.bodySm, color: color.dim, marginTop: space[2] }}>{rec.why}</p>
        <Blurb>{blurb}</Blurb>
      </Panel>
    )
  }

  return (
    <Panel accent label={label} style={{ height: '100%', marginBottom: 0, position: 'relative' }}>
      <div style={{ fontFamily: font.mono, fontSize: 15, color: color.text, fontWeight: 600 }}>
        {rec.harness}
      </div>
      <div
        style={{
          fontFamily: font.mono,
          fontSize: 12,
          color: color.dim,
          marginBottom: space[4],
          overflowWrap: 'anywhere',
        }}
      >
        {rec.model_id}
      </div>

      <Grid cols={2} gap={space[3]}>
        <Metric label="correctness" value={rec.correctness.toFixed(2)} tone="pass" />
        <Metric label="reliability" value={rec.reliability.toFixed(2)} />
        <Metric
          label="avg time"
          value={rec.avg_duration_s ? rec.avg_duration_s.toFixed(0) : '—'}
          unit="s"
        />
        <Metric
          label="avg tokens"
          value={rec.avg_tokens ? Math.round(rec.avg_tokens).toLocaleString() : '—'}
        />
      </Grid>

      {rec.why && (
        <p style={{ ...type.bodySm, color: color.dim, marginTop: space[4] }}>{rec.why}</p>
      )}

      <div style={{ display: 'flex', gap: space[2], marginTop: space[4], flexWrap: 'wrap' }}>
        <Status tone="idle">{rec.completed_reps} reps</Status>
        {rec.statistically_weak && (
          <span title="Fewer than 3 completed repetitions — no significance is claimed">
            <Status tone="warn">statistically weak</Status>
          </span>
        )}
      </div>
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
      <Panel label={title} style={{ marginBottom: 0 }}>
        <Empty>No eligible combinations to plot yet.</Empty>
      </Panel>
    )
  }
  return (
    <Panel label={title} style={{ marginBottom: 0 }}>
      <ResponsiveContainer width="100%" height={230}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke={color.lineSoft} />
          <XAxis
            type="number"
            dataKey="x"
            name={xLabel}
            tick={{ fill: color.faint, fontSize: 10, fontFamily: font.mono }}
            stroke={color.line}
            label={{
              value: xLabel,
              position: 'insideBottom',
              offset: -10,
              fill: color.faint,
              fontSize: 10,
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="correctness"
            domain={[0, 1]}
            tick={{ fill: color.faint, fontSize: 10, fontFamily: font.mono }}
            stroke={color.line}
          />
          <Tooltip
            cursor={{ stroke: color.line }}
            contentStyle={{
              background: color.raised,
              border: `1px solid ${color.line}`,
              borderRadius: radius.md,
              fontFamily: font.mono,
              fontSize: 12,
            }}
            labelFormatter={() => ''}
          />
          <Scatter data={data} isAnimationActive={false}>
            {data.map((d) => (
              // On the frontier = not dominated on both axes. Filled and cyan;
              // everything else stays muted so the frontier reads instantly.
              <Cell
                key={d.id}
                fill={frontier.includes(d.id) ? color.live : 'transparent'}
                stroke={frontier.includes(d.id) ? color.live : color.faint}
                r={6}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div style={{ ...type.caption, color: color.faint, marginTop: space[2] }}>
        filled = on the Pareto frontier (nothing beats it on both axes)
      </div>
    </Panel>
  )
}

const th: React.CSSProperties = {
  ...type.label,
  color: color.faint,
  textAlign: 'left',
  padding: `0 ${space[3]}px ${space[3]}px`,
  whiteSpace: 'nowrap',
  borderBottom: `1px solid ${color.line}`,
}
const thr: React.CSSProperties = { ...th, textAlign: 'right' }
const td: React.CSSProperties = {
  ...type.data,
  padding: `${space[2]}px ${space[3]}px`,
  borderBottom: `1px solid ${color.lineSoft}`,
  whiteSpace: 'nowrap',
}
const tdr: React.CSSProperties = { ...td, textAlign: 'right' }

export default function Results({ experimentId }: { experimentId: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['results', experimentId],
    queryFn: () => api.results(experimentId),
    refetchInterval: 10_000,
  })
  // On demand, not on load: it costs a model call and would be worded
  // differently every time the page refreshed.
  const summary = useMutation({ mutationFn: () => api.summary(experimentId) })

  if (isLoading)
    return (
      <Panel>
        <Empty>Loading results…</Empty>
      </Panel>
    )
  if (isError)
    return <Notice tone="fail">{error instanceof Error ? error.message : 'failed'}</Notice>
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
    .map((c) => ({
      id: c.combination_id,
      label: label(c),
      x: c.mean_tokens!,
      y: c.mean_score ?? 0,
    }))
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

  const caveats = data.caveats ?? []

  return (
    <div>
      <motion.div
        variants={respectMotion(stagger(0.04))}
        initial="hidden"
        animate="shown"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
          gap: space[4],
          marginBottom: space[5],
          alignItems: 'stretch',
        }}
      >
        {CARDS.map((card) => (
          <RecommendationCard
            key={card.key}
            label={card.label}
            blurb={card.blurb}
            rec={data.recommendations[card.key]}
          />
        ))}
      </motion.div>

      {/*
       * The caveats sit directly under the recommendation cards rather than at
       * the foot of the page. Anything qualifying a number has to be readable
       * beside that number, or it may as well not be written.
       */}
      {caveats.length > 0 && (
        <Panel label="Read this before trusting the numbers">
          {caveats.map((caveat) => (
            <div
              key={caveat}
              style={{
                display: 'grid',
                gridTemplateColumns: '14px 1fr',
                gap: space[2],
                ...type.bodySm,
                color: color.dim,
                marginBottom: space[2],
              }}
            >
              <span style={{ color: color.warn }}>—</span>
              <span>{caveat}</span>
            </div>
          ))}
        </Panel>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
          gap: space[4],
          marginBottom: space[5],
        }}
      >
        <ParetoChart
          title="Correctness vs tokens"
          xLabel="mean tokens"
          data={tokenPoints}
          frontier={data.pareto.correctness_vs_tokens ?? []}
        />
        <ParetoChart
          title="Correctness vs duration"
          xLabel="mean seconds"
          data={durationPoints}
          frontier={data.pareto.correctness_vs_duration ?? []}
        />
      </div>

      <Panel label="Every combination">
        <ScrollX>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
            <thead>
              <tr>
                <th style={th}>harness</th>
                <th style={th}>model</th>
                <th style={thr}>runs</th>
                <th style={thr}>success</th>
                <th style={thr}>score</th>
                <th style={thr}>σ</th>
                <th style={thr}>empty patch</th>
                <th style={thr}>tokens</th>
                <th style={thr}>time</th>
                <th style={thr}>weighted</th>
                <th style={th}>status</th>
              </tr>
            </thead>
            <tbody>
              {data.combinations
                .slice()
                .sort((a, b) => (b.weighted_score ?? -1) - (a.weighted_score ?? -1))
                .map((c) => (
                  <tr key={c.combination_id}>
                    <td style={{ ...td, color: color.text }}>{c.harness}</td>
                    <td style={{ ...td, fontSize: 12, color: color.dim }}>
                      {c.model_id.replace(/:free$/, '')}
                    </td>
                    <td style={tdr}>
                      {c.completed}/{c.runs}
                    </td>
                    <td style={{ ...tdr, color: c.success_rate === 1 ? color.pass : color.dim }}>
                      {(c.success_rate * 100).toFixed(0)}%
                    </td>
                    <td style={{ ...tdr, color: c.mean_score ? color.pass : color.dim }}>
                      {c.mean_score === null ? '—' : c.mean_score.toFixed(2)}
                    </td>
                    <td style={{ ...tdr, color: color.dim }}>
                      {c.stdev_score === null ? '—' : c.stdev_score.toFixed(2)}
                    </td>
                    <td style={{ ...tdr, color: c.empty_patch_rate > 0 ? color.warn : color.dim }}>
                      {(c.empty_patch_rate * 100).toFixed(0)}%
                    </td>
                    <td style={{ ...tdr, color: color.dim }}>
                      {c.mean_tokens ? Math.round(c.mean_tokens).toLocaleString() : '—'}
                    </td>
                    <td style={{ ...tdr, color: color.dim }}>
                      {c.mean_duration_s ? `${c.mean_duration_s.toFixed(0)}s` : '—'}
                    </td>
                    <td style={{ ...tdr, color: color.text }}>
                      {c.weighted_score === null ? '—' : c.weighted_score.toFixed(3)}
                    </td>
                    <td style={td}>
                      {c.eligible ? (
                        <Status tone="pass">eligible</Status>
                      ) : (
                        <span title={c.ineligible_reasons.join(' · ')}>
                          <Status tone="warn">excluded</Status>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </ScrollX>
      </Panel>

      <Panel
        label="Which combination did better"
        action={
          <Button
            size="sm"
            disabled={summary.isPending}
            onClick={() => summary.mutate()}
          >
            {summary.isPending ? 'Reading the results…' : 'Write the comparison'}
          </Button>
        }
      >
        {summary.isError && <Notice tone="fail">{(summary.error as Error).message}</Notice>}
        {summary.data?.summary ? (
          <motion.div variants={respectMotion(rise)} initial="hidden" animate="shown">
            <p style={{ ...type.body, color: color.text, whiteSpace: 'pre-wrap' }}>
              {summary.data.summary}
            </p>
            <div style={{ ...type.caption, color: color.faint, marginTop: space[3] }}>
              written by {summary.data.provenance?.model} — reads only the numbers below
            </div>
          </motion.div>
        ) : (
          <Empty>
            Not generated yet. It costs one model call, so it is not written automatically.
          </Empty>
        )}
      </Panel>

      <Panel label="Why combinations were excluded">
        {Object.keys(failureBuckets).length === 0 ? (
          <Empty>Nothing excluded — every combination produced a usable signal.</Empty>
        ) : (
          Object.entries(failureBuckets)
            .sort((a, b) => b[1] - a[1])
            .map(([reason, n]) => (
              <div
                key={reason}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: space[4],
                  padding: `${space[2]}px 0`,
                  borderBottom: `1px solid ${color.lineSoft}`,
                }}
              >
                <span style={{ fontFamily: font.mono, fontSize: 12.5, color: color.dim }}>
                  {reason}
                </span>
                <span style={{ ...type.data, color: color.warn }}>{n}</span>
              </div>
            ))
        )}
      </Panel>
    </div>
  )
}
