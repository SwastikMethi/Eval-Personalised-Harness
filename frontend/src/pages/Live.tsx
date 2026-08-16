import { useMutation, useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { color, radius, space, stateTone } from '../design/tokens'
import { font, type } from '../design/typography'
import {
  Button,
  Empty,
  Metric,
  Notice,
  Panel,
  Row,
  ScreenTitle,
  ScrollX,
  Segmented,
  StackCard,
  Status,
} from '../ui'
import { useStage } from '../stages'
import { useExperimentStream } from '../useExperimentStream'
import Results from './Results'
import RunPanel from './RunPanel'

const fmtSeconds = (s: number | null | undefined) =>
  s === null || s === undefined ? '—' : s < 60 ? `${s.toFixed(0)}s` : `${(s / 60).toFixed(1)}m`

const th: React.CSSProperties = {
  ...type.label,
  color: color.faint,
  textAlign: 'left',
  padding: `0 ${space[3]}px ${space[2]}px`,
  borderBottom: `1px solid ${color.line}`,
  whiteSpace: 'nowrap',
}
const thr: React.CSSProperties = { ...th, textAlign: 'right' }
const td: React.CSSProperties = {
  ...type.data,
  fontSize: 12.5,
  padding: `${space[2]}px ${space[3]}px`,
  borderBottom: `1px solid ${color.lineSoft}`,
  whiteSpace: 'nowrap',
}
const tdr: React.CSSProperties = { ...td, textAlign: 'right' }

export default function Live() {
  const { id } = useParams<{ id: string }>()
  // Live and Results are the last two rail stages, so the rail is what moves
  // between them. An in-content tab bar as well would be the same navigation
  // rendered twice, and the two could disagree.
  const { onResults, setOnResults } = useStage()
  // A freshly opened experiment starts on Live regardless of where the previous
  // one was left.
  useEffect(() => setOnResults(false), [id, setOnResults])
  // Selecting a run opens its detail in place. The old build made this a
  // separate page, which meant losing sight of the matrix to inspect one cell.
  const [selected, setSelected] = useState<string | null>(null)
  // Cards read better, but a 3×4×3 matrix is 36 of them. Null means "decide
  // from the size"; picking either option pins it.
  const [density, setDensity] = useState<'cards' | 'table' | null>(null)
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

  const pause = useMutation({ mutationFn: () => api.pause(id!) })
  const resume = useMutation({ mutationFn: () => api.resume(id!) })
  const cancelAll = useMutation({ mutationFn: () => api.cancelExperiment(id!) })

  const state = progress ?? polled.data ?? null
  const pct = state && state.total ? (state.done / state.total) * 100 : 0
  const active =
    state?.runs.filter((r) => ['RUNNING', 'PREPARING', 'EVALUATING'].includes(r.state)) ?? []
  const throttled = state?.runs.filter((r) => r.rate_limited || r.state === 'RATE_LIMITED') ?? []
  const totalRequests = state?.runs.reduce((n, r) => n + (r.model_requests ?? 0), 0) ?? 0
  const totalTokens =
    state?.runs.reduce((n, r) => n + (r.input_tokens ?? 0) + (r.output_tokens ?? 0), 0) ?? 0

  const CARD_LIMIT = 12
  const dense = density === null ? (state?.runs.length ?? 0) > CARD_LIMIT : density === 'table'

  return (
    <div>
      {!onResults && (
      <ScreenTitle
        ask="What are the agents doing?"
        title={meta.data?.name ?? 'Experiment'}
        lede={
          state?.finished
            ? 'Finished. Results ranks every stack that produced a usable signal.'
            : `${state?.done ?? 0} of ${state?.total ?? 0} complete · each card is one repetition of one stack.`
        }
        action={
          !state?.finished && (
            <Row gap={space[2]}>
              <Button size="sm" disabled={pause.isPending} onClick={() => pause.mutate()}>
                Pause
              </Button>
              <Button size="sm" disabled={resume.isPending} onClick={() => resume.mutate()}>
                Resume
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={cancelAll.isPending}
                onClick={() => cancelAll.mutate()}
              >
                Cancel experiment
              </Button>
            </Row>
          )
        }
      />
      )}

      {!onResults && (
      <Panel style={{ padding: 0, overflow: 'hidden' }}>
        <div
          style={{
            padding: space[5],
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(112px, 1fr))',
            gap: space[4],
          }}
        >
          <Metric
            label="progress"
            value={`${state?.done ?? 0}/${state?.total ?? 0}`}
            tone={state?.finished ? 'pass' : 'live'}
          />
          <Metric label="active" value={active.length} tone={active.length ? 'live' : undefined} />
          <Metric
            label="throttled"
            value={throttled.length}
            tone={throttled.length ? 'warn' : undefined}
          />
          <Metric label="model requests" value={totalRequests} />
          <Metric label="tokens" value={totalTokens.toLocaleString()} />
          <Metric
            label="stream"
            value={connected ? 'live' : finished ? 'closed' : 'polling'}
            tone={connected ? 'live' : undefined}
          />
        </div>
        {/* A real measurement growing to its value — the one place a bar
            animating is information rather than decoration. */}
        <div style={{ height: 3, background: color.lineSoft }}>
          <motion.div
            animate={{ scaleX: pct / 100 }}
            initial={{ scaleX: 0 }}
            transition={{ duration: 0.6, ease: [0.2, 0.7, 0.3, 1] }}
            style={{
              height: '100%',
              transformOrigin: 'left',
              background: state?.finished ? color.pass : color.live,
            }}
          />
        </div>
      </Panel>
      )}

      {!onResults && throttled.length > 0 && (
        <Notice tone="warn">
          {throttled.length} run{throttled.length === 1 ? '' : 's'} hit provider rate limits. They
          are parked and resume automatically with backoff — nothing is lost, the matrix just takes
          longer.
        </Notice>
      )}

      {!onResults && (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 2fr) minmax(260px, 1fr)',
              gap: space[4],
              alignItems: 'start',
            }}
          >
            <Panel
              label={`Runs · ${state?.runs.length ?? 0}`}
              action={
                (state?.runs.length ?? 0) > 0 && (
                  <Segmented
                    value={dense ? 'table' : 'cards'}
                    onChange={(v) => setDensity(v)}
                    options={[
                      { value: 'cards' as const, label: 'Cards' },
                      { value: 'table' as const, label: 'Table' },
                    ]}
                  />
                )
              }
            >
              {!state || state.runs.length === 0 ? (
                <Empty>No runs queued yet.</Empty>
              ) : !dense ? (
                /* One card per run. Reads far better than a table at the sizes a
                   free-tier matrix actually runs at, and it makes the thing being
                   compared — the stack — the visible unit. */
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
                    gap: space[3],
                  }}
                >
                  {state.runs.map((r) => {
                    const on = selected === r.run_id
                    const live = ['RUNNING', 'PREPARING', 'EVALUATING'].includes(r.state)
                    return (
                      <StackCard
                        key={r.run_id}
                        selected={on}
                        onClick={() => setSelected(on ? null : r.run_id)}
                        ariaLabel={`${on ? 'close' : 'inspect'} ${r.harness} × ${r.model_id}`}
                        harness={r.harness}
                        model={r.model_id.replace(/:free$/, '')}
                        status={
                          <Status tone={stateTone(r.state)} pulse={live}>
                            {r.state.toLowerCase()}
                          </Status>
                        }
                        footer={
                          <>
                            <span style={{ ...type.caption, color: color.faint }}>
                              {r.model_requests ?? 0} call
                              {r.model_requests === 1 ? '' : 's'} · {fmtSeconds(r.elapsed_s)}
                            </span>
                            <span
                              style={{
                                ...type.caption,
                                color:
                                  r.score !== null && r.score !== undefined
                                    ? color.pass
                                    : color.faint,
                              }}
                            >
                              {r.score === null || r.score === undefined
                                ? r.budget_exhausted
                                  ? 'budget spent'
                                  : '—'
                                : r.score.toFixed(3)}
                            </span>
                          </>
                        }
                      />
                    )
                  })}
                </div>
              ) : (
                <ScrollX>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 700 }}>
                    <thead>
                      <tr>
                        <th style={th}>harness</th>
                        <th style={th}>model</th>
                        <th style={thr}>rep</th>
                        <th style={th}>state</th>
                        <th style={thr}>elapsed</th>
                        <th style={thr}>req</th>
                        <th style={thr}>tokens</th>
                        <th style={thr}>score</th>
                        <th style={th} />
                      </tr>
                    </thead>
                    <tbody>
                      {state.runs.map((r) => {
                        const on = selected === r.run_id
                        return (
                          // Clicking the row is the mouse convenience; the
                          // button in the last cell is the real control, so the
                          // row needs no ARIA of its own and keyboard users get
                          // a properly named target rather than a focusable <tr>.
                          <tr
                            key={r.run_id}
                            onClick={() => setSelected(on ? null : r.run_id)}
                            style={{
                              cursor: 'pointer',
                              background: on ? color.raised : undefined,
                            }}
                          >
                            <td style={{ ...td, color: color.text }}>{r.harness}</td>
                            <td style={{ ...td, fontSize: 12, color: color.dim }} title={r.model_id}>
                              {r.model_id.replace(/:free$/, '')}
                            </td>
                            <td style={tdr}>{r.repetition}</td>
                            <td style={td}>
                              <Row gap={6}>
                                <Status
                                  tone={stateTone(r.state)}
                                  pulse={['RUNNING', 'PREPARING', 'EVALUATING'].includes(r.state)}
                                >
                                  {r.state}
                                </Status>
                                {r.budget_exhausted && (
                                  <span
                                    title="Used its entire model-request budget"
                                    style={{ ...type.caption, color: color.warn }}
                                  >
                                    budget
                                  </span>
                                )}
                              </Row>
                            </td>
                            <td style={tdr}>{fmtSeconds(r.elapsed_s)}</td>
                            <td style={tdr}>{r.model_requests ?? '—'}</td>
                            <td style={tdr}>
                              {r.input_tokens || r.output_tokens
                                ? (
                                    (r.input_tokens ?? 0) + (r.output_tokens ?? 0)
                                  ).toLocaleString()
                                : '—'}
                            </td>
                            <td style={{ ...tdr, color: r.score ? color.pass : color.dim }}>
                              {r.score === null || r.score === undefined
                                ? '—'
                                : r.score.toFixed(2)}
                            </td>
                            <td style={tdr}>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setSelected(on ? null : r.run_id)}
                              >
                                {on ? 'close' : 'inspect'}
                              </Button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </ScrollX>
              )}
              <div style={{ ...type.caption, color: color.faint, marginTop: space[3] }}>
                select a run to inspect it
              </div>
            </Panel>

            <Panel label="Activity">
              {events.length === 0 ? (
                <Empty>Waiting for the first event…</Empty>
              ) : (
                <div style={{ maxHeight: 520, overflowY: 'auto' }}>
                  <AnimatePresence initial={false}>
                    {events.map((e, i) => (
                      <motion.div
                        key={`${e.run_id}-${e.at}-${i}`}
                        initial={{ opacity: 0, y: -4 }}
                        animate={{ opacity: 1, y: 0 }}
                        style={{
                          display: 'flex',
                          gap: space[2],
                          alignItems: 'center',
                          padding: `${space[2]}px 0`,
                          borderBottom: `1px solid ${color.lineSoft}`,
                        }}
                      >
                        <span style={{ ...type.caption, color: color.faint }}>
                          {e.at.slice(11, 19)}
                        </span>
                        <span style={{ fontFamily: font.mono, fontSize: 12, color: color.text }}>
                          {e.type}
                        </span>
                        <span style={{ flexGrow: 1 }} />
                        <span style={{ ...type.caption, color: color.faint }}>
                          {e.run_id.slice(0, 6)}
                        </span>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              )}
            </Panel>
          </div>

          {selected && (
            <div style={{ marginTop: space[4] }}>
              <Row style={{ justifyContent: 'space-between', marginBottom: space[3] }}>
                <span style={{ ...type.label, color: color.faint }}>Selected run</span>
                <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
                  Close
                </Button>
              </Row>
              <div
                style={{
                  borderLeft: `2px solid ${color.line}`,
                  paddingLeft: space[4],
                  borderRadius: radius.sm,
                }}
              >
                <RunPanel key={selected} runId={selected} />
              </div>
            </div>
          )}
        </>
      )}

      {onResults && <Results experimentId={id!} experimentName={meta.data?.name} />}
    </div>
  )
}
