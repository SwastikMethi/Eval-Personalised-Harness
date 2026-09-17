import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
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
import { font, type } from '../design/typography'
import {
  Bar,
  Button,
  Empty,
  Hero,
  Notice,
  Panel,
  ScreenTitle,
  ScrollX,
  StepItem,
  Steps,
  Status,
  Tabs,
} from '../ui'

/**
 * Which stack should I use?
 *
 * The recommendation comes first and everything else argues with it. An earlier
 * build opened with four equally-weighted cards, which handed the ranking back
 * to the reader — exactly the work this tool exists to do.
 */

const DIMENSIONS = [
  { key: 'best_balanced', label: 'Best balanced', blurb: 'weighted across all dimensions' },
  { key: 'best_quality', label: 'Best quality', blurb: 'highest correctness' },
  { key: 'best_reliability', label: 'Best reliability', blurb: 'most consistent across repetitions' },
  {
    key: 'best_efficiency',
    label: 'Best efficiency',
    blurb: 'least time and tokens, correctness-gated',
  },
] as const

// Right-aligned columns need padding on the LEFT, or a narrow header like "σ"
// butts straight against the one before it and reads as one word.
const th: React.CSSProperties = {
  ...type.label,
  color: color.faint,
  textAlign: 'left',
  padding: `0 ${space[3]}px ${space[2]}px 0`,
  whiteSpace: 'nowrap',
  borderBottom: `1px solid ${color.line}`,
}
const thr: React.CSSProperties = {
  ...th,
  textAlign: 'right',
  padding: `0 0 ${space[2]}px ${space[4]}px`,
}
const td: React.CSSProperties = {
  ...type.data,
  padding: `11px ${space[3]}px 11px 0`,
  borderBottom: `1px solid ${color.lineSoft}`,
  whiteSpace: 'nowrap',
}
const tdr: React.CSSProperties = {
  ...td,
  textAlign: 'right',
  padding: `11px 0 11px ${space[4]}px`,
}

/** The winner, stated. Or an honest refusal to name one. */
function Verdict({
  dimension,
  rec,
  blurb,
}: {
  dimension: string
  rec: ComboRecommendation | undefined
  blurb: string
}) {
  if (!rec)
    return (
      <Hero muted label={dimension} name="No eligible combination">
        <p style={{ ...type.bodySm, color: color.dim, marginTop: space[3] }}>
          Nothing produced a usable signal on this dimension. {blurb}.
        </p>
      </Hero>
    )

  // A tie is a result. Printing a name here would overstate it, and this is the
  // most-read thing on the page.
  if (rec.tied)
    return (
      <Hero muted label={dimension} name="No winner">
        <p style={{ ...type.bodySm, color: color.dim, marginTop: space[3], maxWidth: '64ch' }}>
          {rec.why}
        </p>
      </Hero>
    )

  const met = Math.round(rec.correctness * 6)
  return (
    <Hero
      label={dimension}
      name={`${rec.harness} × ${rec.model_id.replace(/:free$/, '')}`}
      score={rec.correctness.toFixed(2)}
      detail={`${rec.completed_reps} repetition${rec.completed_reps === 1 ? '' : 's'} completed · reliability ${rec.reliability.toFixed(2)}`}
      note={
        rec.avg_duration_s
          ? `${rec.avg_duration_s.toFixed(0)}s average · ${
              rec.avg_tokens ? Math.round(rec.avg_tokens).toLocaleString() : '—'
            } tokens`
          : undefined
      }
      composition={Array.from({ length: 6 }, (_, i) => (i < met ? 'pass' : 'warn'))}
    >
      {rec.why && (
        <p style={{ ...type.bodySm, color: color.dim, marginTop: space[4], maxWidth: '64ch' }}>
          {rec.why}
        </p>
      )}
      {/* The product's own term, kept verbatim rather than paraphrased — it is
          the same phrase the caveats and the backend field use, and a hedge
          that reads differently in each place stops registering as a hedge. */}
      {rec.statistically_weak && (
        <div style={{ marginTop: space[4] }}>
          <span title="Fewer than 3 completed repetitions — no significance is claimed">
            <Status tone="warn">statistically weak</Status>
          </span>
        </div>
      )}
    </Hero>
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
  if (data.length === 0)
    return (
      <Panel label={title} style={{ marginBottom: 0 }}>
        <Empty>No eligible combinations to plot yet.</Empty>
      </Panel>
    )
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

export default function Results({
  experimentId,
  experimentName,
}: {
  experimentId: string
  experimentName?: string
}) {
  const [dimension, setDimension] = useState<string>(DIMENSIONS[0].label)
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
  const active = DIMENSIONS.find((d) => d.label === dimension) ?? DIMENSIONS[0]
  const rec = data.recommendations[active.key]

  const ranked = data.combinations
    .slice()
    .sort((a, b) => (b.mean_score ?? -1) - (a.mean_score ?? -1))
  const top = ranked[0]?.mean_score ?? 0
  const winnerId = rec && !rec.tied ? `${rec.harness}${rec.model_id}` : null

  return (
    <div>
      <ScreenTitle
        ask="Which stack should I use?"
        title="Results"
        lede={
          experimentName
            ? `${experimentName} · the recommendation comes first, everything below is for arguing with it.`
            : 'The recommendation comes first. Everything below is for arguing with it.'
        }
      />

      {/* Four dimensions, one at a time. Showing all four at equal weight was
          what made the page feel like a report rather than an answer. */}
      <Tabs tabs={DIMENSIONS.map((d) => d.label)} active={dimension} onSelect={setDimension} />

      <Verdict dimension={active.label} rec={rec} blurb={active.blurb} />

      {/* Qualifications sit with the number they qualify, not at the page foot. */}
      {caveats.length > 0 && (
        <Panel label="Read this before trusting the numbers">
          <Steps>
            {caveats.map((c) => (
              <StepItem key={c} state="failed">
                {c}
              </StepItem>
            ))}
          </Steps>
        </Panel>
      )}

      <Panel label="Comparison">
        <div style={{ display: 'grid', gap: 10, marginBottom: space[5] }}>
          {ranked.map((c) => {
            const isWinner = winnerId === `${c.harness}${c.model_id}`
            return (
              <Bar
                key={c.combination_id}
                who={label(c)}
                pct={c.mean_score !== null && top > 0 ? (c.mean_score / top) * 100 : 0}
                muted={!isWinner}
                value={c.mean_score === null ? 'n/a' : c.mean_score.toFixed(2)}
              />
            )
          })}
        </div>

        <ScrollX>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
            <thead>
              <tr>
                <th style={th}>stack</th>
                <th style={thr}>runs</th>
                {/* Not "success": this counts runs scoring at or above 0.5,
                    so a recommended stack could read "0% success" while an
                    excluded one read 100% — two correct numbers that together
                    looked like a contradiction. Name the threshold instead. */}
                <th style={thr} title="share of runs scoring 0.50 or higher">
                  ≥ 0.50
                </th>
                <th style={thr}>score</th>
                <th style={thr}>σ</th>
                <th style={thr}>empty patch</th>
                <th style={thr}>tokens</th>
                <th style={thr}>time</th>
                <th style={thr}>weighted</th>
                {/* Left padding, or it runs straight into the right-aligned
                    "weighted" before it and reads as one word. */}
                <th style={{ ...th, paddingLeft: space[4] }}>status</th>
              </tr>
            </thead>
            <tbody>
              {data.combinations
                .slice()
                .sort((a, b) => (b.weighted_score ?? -1) - (a.weighted_score ?? -1))
                .map((c) => (
                  <tr key={c.combination_id}>
                    <td style={{ ...td, color: c.eligible ? color.text : color.faint }}>
                      {c.harness} × {c.model_id.replace(/:free$/, '')}
                    </td>
                    <td style={tdr}>
                      {c.completed}/{c.runs}
                    </td>
                    <td style={{ ...tdr, color: c.success_rate === 1 ? color.pass : color.dim }}>
                      {(c.success_rate * 100).toFixed(0)}%
                    </td>
                    <td style={{ ...tdr, color: c.mean_score ? color.pass : color.faint }}>
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
                    <td style={{ ...td, paddingLeft: space[4] }}>
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
          <Button size="sm" disabled={summary.isPending} onClick={() => summary.mutate()}>
            {summary.isPending ? 'Reading the results…' : 'Write the comparison'}
          </Button>
        }
      >
        {summary.isError && <Notice tone="fail">{(summary.error as Error).message}</Notice>}
        {summary.data?.summary ? (
          <>
            <p style={{ ...type.body, color: color.text, whiteSpace: 'pre-wrap' }}>
              {summary.data.summary}
            </p>
            <div style={{ ...type.caption, color: color.faint, marginTop: space[3] }}>
              written by {summary.data.provenance?.model} — reads only the numbers above
            </div>
          </>
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
          <Steps>
            {Object.entries(failureBuckets)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => (
                <StepItem key={reason} state="failed">
                  {reason} <span style={{ color: color.faint }}>· {n}</span>
                </StepItem>
              ))}
          </Steps>
        )}
      </Panel>

      {/* Below the fold on purpose: the charts are evidence, not the answer. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
          gap: space[4],
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
    </div>
  )
}
