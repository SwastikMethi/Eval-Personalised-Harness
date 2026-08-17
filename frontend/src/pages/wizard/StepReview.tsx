import { color, space } from '../../design/tokens'
import { font, type } from '../../design/typography'
import { Button, Field, Metric, Notice, Panel, Row, ScreenTitle, StepItem, Steps } from '../../ui'
import SetupPanel from './SetupPanel'
import { DAILY_FREE_REQUESTS, type Wizard } from './useWizard'

/**
 * Review — "what exactly will happen?"
 *
 * The last screen before anything is spent, so it is the one place that must not
 * be optimistic: the arithmetic, the cost, the caveats and every blocker, all
 * visible together.
 */
export default function StepReview({ w }: { w: Wizard }) {
  const preview = w.preview

  return (
    <>
      <ScreenTitle
        ask="What exactly will happen?"
        title={w.blockers.length === 0 ? 'Ready to run' : 'Not ready yet'}
        lede="Nothing is queued and nothing is spent until you start. This is the last screen before either."
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) minmax(320px, 1fr)',
          gap: space[4],
          alignItems: 'start',
        }}
      >
      <div>
        <Panel label="Matrix">
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
              gap: space[3],
              marginBottom: space[4],
            }}
          >
            <Field
              label="repetitions"
              type="number"
              min={1}
              value={w.reps}
              onChange={(v) => w.setReps(Math.max(1, Number(v)))}
            />
          </div>

          {/* No request cap. A request count never bounded spend anyway —
              100 calls cost anywhere from 100k to 3M tokens depending on how
              much history the harness resends — so the run is bounded by the
              30-minute timeout and the token ceiling instead. */}
          <div style={{ ...type.caption, color: color.faint, margin: `0 0 ${space[4]}px` }}>
            bounded by the 30-minute timeout and the token ceiling; the agent stops when it is
            finished rather than when an allowance runs out
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: space[4] }}>
            <tbody>
              {(
                [
                  ['stacks', w.stacks.length],
                  [w.sharedGroups > 0 ? 'task groups' : 'tasks', w.taskGroups],
                  ['repetitions', w.reps],
                ] as const
              ).map(([k, v]) => (
                <tr key={k}>
                  <td
                    style={{
                      padding: '3px 0',
                      fontFamily: font.mono,
                      fontSize: 12,
                      color: color.faint,
                    }}
                  >
                    {k}
                  </td>
                  <td
                    style={{
                      padding: '3px 0',
                      textAlign: 'right',
                      ...type.data,
                      color: color.text,
                    }}
                  >
                    {v}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: space[3],
              paddingTop: space[4],
              borderTop: `1px solid ${color.line}`,
            }}
          >
            <Metric label="total runs" value={w.runs} tone={w.runs ? 'live' : undefined} />
            {w.cappedStacks.length > 0 ? (
              <Metric
                label="openrouter requests"
                value={`~${w.requests}`}
                tone={w.overDailyCap ? 'warn' : 'pass'}
                sub={`free tier ≈ ${DAILY_FREE_REQUESTS}/day`}
              />
            ) : (
              <Metric label="daily quota" value="n/a" sub="no free-tier stack" />
            )}
          </div>

          {/* Server-side expansion. If it ever disagrees with the arithmetic
              above, the server is right and the user needs to know before
              queueing rather than after. */}
          {preview.data && (
            <div style={{ marginTop: space[3] }}>
              {preview.data.runs === w.runs ? (
                <div style={{ ...type.caption, color: color.faint }}>
                  confirmed by the server · {preview.data.expression}
                </div>
              ) : (
                <Notice tone="warn">
                  The server expands this to {preview.data.runs} runs ({preview.data.expression}),
                  not {w.runs}. Its count is the one that will be queued.
                </Notice>
              )}
            </div>
          )}

          {w.reps < 3 && w.runs > 0 && (
            <div style={{ marginTop: space[3] }}>
              <Notice tone="info">
                Under 3 repetitions every result is flagged statistically weak. Fine for a smoke
                test; not enough for a reliability claim.
              </Notice>
            </div>
          )}
          {w.overDailyCap && (
            <div style={{ marginTop: space[3] }}>
              <Notice tone="warn">
                {w.cappedStacks.length} of your {w.stacks.length} stack
                {w.stacks.length === 1 ? '' : 's'} run on OpenRouter, whose free tier allows
                roughly {DAILY_FREE_REQUESTS} requests a day; this looks like about {w.requests}.
                Runs that hit the limit are parked and resume automatically, so the matrix takes
                longer rather than failing. Stacks on other providers are not subject to it.
              </Notice>
            </div>
          )}
        </Panel>

        <Panel label="Stacks entered">
          {w.stacks.length === 0 ? (
            <div style={{ ...type.bodySm, color: color.faint }}>Nothing selected yet.</div>
          ) : (
            w.stacks.map((s) => (
              <div
                key={`${s.harness}-${s.provider}-${s.model_id}`}
                style={{
                  display: 'flex',
                  gap: space[2],
                  alignItems: 'baseline',
                  padding: `${space[2]}px 0`,
                  borderBottom: `1px solid ${color.lineSoft}`,
                  fontFamily: font.mono,
                  fontSize: 12.5,
                }}
              >
                <span style={{ color: color.text }}>{s.harness}</span>
                <span style={{ color: color.faint }}>×</span>
                <span style={{ color: color.dim }}>{s.model_id.replace(/:free$/, '')}</span>
                <span style={{ flexGrow: 1 }} />
                {/* The provider is part of the stack's identity now, so it has
                    to be visible in the last review before anything is spent. */}
                <span style={{ ...type.caption, color: color.faint }}>{s.provider}</span>
              </div>
            ))
          )}
        </Panel>
      </div>

      <div>
        <SetupPanel w={w} />

        <Button
          variant="primary"
          disabled={w.blockers.length > 0 || w.launch.isPending}
          onClick={() => w.launch.mutate()}
          style={{ width: '100%', padding: '12px 20px', fontSize: 14 }}
        >
          {/* Naming the step matters: creation first verifies every model can
              actually be called, which takes as long as one model call.
              Unlabelled, that read as a hang. */}
          {w.launch.isPending
            ? 'Verifying models…'
            : `Start ${w.runs} run${w.runs === 1 ? '' : 's'}`}
        </Button>

        {w.launch.isPending && (
          <div style={{ ...type.caption, color: color.faint, marginTop: space[2] }}>
            checking each model answers on this account before queueing anything
          </div>
        )}
        {w.launch.isError && (
          // Shown here, next to the selection that caused it, rather than only
          // as a toast that scrolls away from the models to change.
          <div style={{ ...type.caption, color: color.warn, marginTop: space[2] }}>
            {(w.launch.error as Error).message}
          </div>
        )}

        {/* Every blocker, not just the first — hiding the rest makes the button
            feel like it never unlocks. */}
        {w.blockers.length > 0 && (
          <div style={{ marginTop: space[4] }}>
            <Steps>
              {w.blockers.map((reason) => (
                <StepItem key={reason} state="failed">
                  {reason}
                </StepItem>
              ))}
            </Steps>
          </div>
        )}

        <Row style={{ marginTop: space[4] }}>
          <Button size="sm" variant="ghost" onClick={() => w.setStep(2)}>
            ← Back to stacks
          </Button>
        </Row>
        </div>
      </div>
    </>
  )
}
