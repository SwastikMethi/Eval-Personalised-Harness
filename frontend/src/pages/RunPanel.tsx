import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { api } from '../api'
import type { JudgeVerdict } from '../api'
import { color, space, stateTone } from '../design/tokens'
import { respectMotion, rise } from '../design/motion'
import { font, type } from '../design/typography'
import {
  Button,
  Criterion,
  Empty,
  Metric,
  Notice,
  Panel,
  Row,
  Rubric,
  ScrollX,
  Status,
  Tabs,
} from '../ui'
import { useState } from 'react'

/**
 * A unified diff, coloured by line kind. Rendered as spans inside one <pre> so
 * the whole patch stays selectable and copyable as text.
 */
function Diff({ patch }: { patch: string }) {
  return (
    <pre
      style={{
        margin: 0,
        padding: space[4],
        overflowX: 'auto',
        background: color.bg,
        border: `1px solid ${color.lineSoft}`,
        borderRadius: 6,
        fontFamily: font.mono,
        fontSize: 12,
        lineHeight: 1.6,
        maxHeight: 460,
      }}
    >
      {patch.split('\n').map((line, i) => {
        const c =
          line.startsWith('+++') || line.startsWith('---')
            ? color.dim
            : line.startsWith('+')
              ? color.pass
              : line.startsWith('-')
                ? color.fail
                : line.startsWith('@@')
                  ? color.live
                  : color.dim
        return (
          <span key={i} style={{ color: c, display: 'block', whiteSpace: 'pre' }}>
            {line || ' '}
          </span>
        )
      })}
    </pre>
  )
}

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
  fontSize: 12,
  padding: `${space[2]}px ${space[3]}px`,
  borderBottom: `1px solid ${color.lineSoft}`,
  whiteSpace: 'nowrap',
}
const tdr: React.CSSProperties = { ...td, textAlign: 'right' }

const TABS = ['Patch', 'Evaluation', 'Timeline', 'Model calls']

/**
 * Everything known about one run. Rendered inline inside Live when a row is
 * selected, and standalone at /runs/:id so a run stays linkable.
 */
export default function RunPanel({ runId }: { runId: string }) {
  const [tab, setTab] = useState(TABS[0])
  const qc = useQueryClient()

  const detail = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.runDetail(runId),
    refetchInterval: (q) =>
      ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'].includes(q.state.data?.state ?? '')
        ? false
        : 3000,
  })
  const patch = useQuery({
    queryKey: ['patch', runId],
    queryFn: () => api.runPatch(runId),
    enabled: Boolean(detail.data?.has_patch),
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['run', runId] })
  const retry = useMutation({ mutationFn: () => api.retryRun(runId), onSuccess: invalidate })
  // The UI could start work but never stop it. A single run is exactly the
  // granularity you want when one pair is stuck and the rest of the matrix is fine.
  const cancel = useMutation({ mutationFn: () => api.cancelRun(runId), onSuccess: invalidate })

  if (detail.isLoading)
    return (
      <Panel>
        <Empty>Loading run…</Empty>
      </Panel>
    )
  if (detail.isError || !detail.data) return <Notice tone="fail">Run not found.</Notice>

  const d = detail.data
  const usage = d.usage ?? {}
  const ev = d.evaluation
  const results = ev?.results ?? {}
  // The evaluation payload is an open record of evaluator name → result, so the
  // judge entry has to be named to be read safely. Partial<> because an
  // evaluator that errored returns only `error`.
  const judge: Partial<JudgeVerdict> | undefined = results.judge
  const running = !['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'].includes(d.state)

  return (
    <motion.div variants={respectMotion(rise)} initial="hidden" animate="shown">
      <Panel>
        <Row style={{ justifyContent: 'space-between', marginBottom: space[4] }}>
          <div>
            <div style={{ ...type.subheading, color: color.text }}>
              {d.harness ?? 'run'} · {(d.model_id ?? '').replace(/:free$/, '')}
            </div>
            {d.task?.title && (
              <div style={{ ...type.bodySm, color: color.dim }}>{d.task.title}</div>
            )}
          </div>
          <Row gap={space[2]}>
            <Status tone={stateTone(d.state)} pulse={running}>
              {d.state}
            </Status>
            {running && (
              <Button
                size="sm"
                variant="danger"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate()}
              >
                {cancel.isPending ? 'Cancelling…' : 'Cancel run'}
              </Button>
            )}
            {['FAILED', 'TIMED_OUT'].includes(d.state) && (
              <Button size="sm" disabled={retry.isPending} onClick={() => retry.mutate()}>
                {retry.isPending ? 'Retrying…' : 'Retry'}
              </Button>
            )}
          </Row>
        </Row>

        {cancel.isError && <Notice tone="fail">{(cancel.error as Error).message}</Notice>}
        {retry.isError && <Notice tone="fail">{(retry.error as Error).message}</Notice>}

        {d.error_message && (
          <Notice tone={d.state === 'FAILED' ? 'fail' : 'warn'}>
            <span style={{ fontFamily: font.mono, fontSize: 12 }}>
              [{d.error_category}] {d.error_message.slice(0, 600)}
            </span>
          </Notice>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
            gap: space[4],
          }}
        >
          <Metric label="repetition" value={d.repetition} />
          <Metric label="requests" value={String(usage.requests ?? '—')} />
          <Metric label="input tok" value={Number(usage.input_tokens ?? 0).toLocaleString()} />
          <Metric label="output tok" value={Number(usage.output_tokens ?? 0).toLocaleString()} />
          <Metric
            label="cost"
            value={`$${Number(usage.cost_usd ?? 0).toFixed(4)}`}
            sub="free models record $0"
          />
          <Metric
            label="score"
            value={ev?.score === null || ev?.score === undefined ? '—' : ev.score.toFixed(2)}
            tone={ev?.score ? 'pass' : undefined}
          />
          {usage.rate_limited ? <Metric label="throttled" value="yes" tone="warn" /> : null}
          {usage.budget_exhausted ? <Metric label="budget" value="spent" tone="warn" /> : null}
        </div>
      </Panel>

      <Panel>
        <Tabs tabs={TABS} active={tab} onSelect={setTab} />

        {tab === 'Patch' &&
          (!d.has_patch ? (
            <Empty>
              No patch produced. That is a legitimate benchmark result — it scores zero rather than
              being treated as an error.
            </Empty>
          ) : patch.isLoading ? (
            <Empty>Loading patch…</Empty>
          ) : patch.data ? (
            <Diff patch={patch.data.patch} />
          ) : (
            <Empty>Patch artifact missing from disk.</Empty>
          ))}

        {tab === 'Evaluation' &&
          (!ev ? (
            <Empty>Not evaluated.</Empty>
          ) : (
            <>
              <div style={{ marginBottom: space[4] }}>
                <Metric label="signal" value={ev.signal} tone={ev.signal === 'ok' ? 'pass' : 'warn'} />
              </div>
              {/* The rubric verdict, legibly. It is in the raw dump below too,
                  but "which criteria did this answer actually meet" is the whole
                  result of a comprehension run and should not need reading JSON. */}
              {judge && (
                <div style={{ marginBottom: space[4] }}>
                  <p style={{ ...type.bodySm, color: color.dim, marginBottom: space[3] }}>
                    {judge.rationale || 'graded against the task rubric'}
                  </p>
                  {/* Same grid the rubric was written in, now carrying the
                      verdict column — so a score can be read against the exact
                      list it was graded on rather than three loose lists. */}
                  <Rubric>
                    {(judge.met ?? []).map((c: string) => (
                      <Criterion key={c} verdict="met">
                        {c}
                      </Criterion>
                    ))}
                    {(judge.partial ?? []).map((c: string) => (
                      <Criterion key={c} verdict="partial">
                        {c}
                      </Criterion>
                    ))}
                    {(judge.missing ?? []).map((c: string) => (
                      <Criterion key={c} verdict="missed">
                        {c}
                      </Criterion>
                    ))}
                  </Rubric>
                  {(judge.invented ?? []).length > 0 && (
                    <Notice tone="warn">
                      Named things that do not exist in this repository:{' '}
                      {(judge.invented ?? []).join(', ')}
                    </Notice>
                  )}
                  {judge.error && <Notice tone="fail">{judge.error}</Notice>}
                  <div style={{ ...type.caption, color: color.faint, marginTop: space[3] }}>
                    answer read from {results.answer_source} · {results.answer_chars} chars
                  </div>
                </div>
              )}
              {Object.entries(results).map(([name, value]) => (
                <div
                  key={name}
                  style={{ padding: `${space[2]}px 0`, borderBottom: `1px solid ${color.lineSoft}` }}
                >
                  <div style={{ fontFamily: font.mono, fontSize: 12, color: color.text }}>
                    {name}
                  </div>
                  <div
                    style={{
                      fontFamily: font.mono,
                      fontSize: 11.5,
                      color: color.dim,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {JSON.stringify(value)}
                  </div>
                </div>
              ))}
            </>
          ))}

        {tab === 'Timeline' &&
          (d.timeline.length === 0 ? (
            <Empty>No events.</Empty>
          ) : (
            d.timeline.map((e, i) => (
              <div key={i} style={{ display: 'flex', gap: space[3], padding: `${space[2]}px 0` }}>
                <span style={{ ...type.caption, color: color.faint }}>{e.at.slice(11, 19)}</span>
                <span style={{ fontFamily: font.mono, fontSize: 12.5, color: color.text }}>
                  {e.type}
                </span>
              </div>
            ))
          ))}

        {tab === 'Model calls' &&
          (d.model_requests.length === 0 ? (
            <Empty>The agent never called the model.</Empty>
          ) : (
            <ScrollX>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 460 }}>
                <thead>
                  <tr>
                    <th style={th}>status</th>
                    <th style={thr}>latency</th>
                    <th style={thr}>in</th>
                    <th style={thr}>out</th>
                    <th style={th}>provider</th>
                  </tr>
                </thead>
                <tbody>
                  {d.model_requests.map((m, i) => (
                    <tr key={i}>
                      <td
                        style={{ ...td, color: m.http_status === 200 ? color.pass : color.warn }}
                      >
                        {m.http_status}
                      </td>
                      <td style={tdr}>{m.latency_ms}ms</td>
                      <td style={tdr}>{m.input_tokens ?? '—'}</td>
                      <td style={tdr}>{m.output_tokens ?? '—'}</td>
                      <td style={{ ...td, color: color.dim }}>{m.routed_provider ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollX>
          ))}
      </Panel>
    </motion.div>
  )
}
