import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { color, space } from '../../design/tokens'
import { font, type } from '../../design/typography'
import { Button, Check, Field, Metric, Notice, Panel, Row } from '../../ui'
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
  // The backend already computes this expansion. Showing its answer rather than
  // ours means the number on screen is the number that will be queued.
  const preview = useQuery({
    queryKey: ['preview', w.taskIds, w.harnesses, w.models, w.reps],
    queryFn: () =>
      api.preview({
        task_ids: w.taskIds,
        harnesses: w.harnesses,
        model_ids: w.models,
        repetitions: w.reps,
      }),
    enabled: w.taskIds.length > 0 && w.harnesses.length > 0 && w.models.length > 0,
    retry: false,
  })

  return (
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
            <Field
              label="requests / run"
              type="number"
              min={1}
              disabled={w.uncapped}
              value={w.budget}
              onChange={(v) => w.setBudget(Math.max(1, Number(v)))}
            />
            <Field
              label="steps / run"
              type="number"
              min={1}
              value={w.steps}
              onChange={(v) => w.setSteps(Math.max(1, Number(v)))}
            />
          </div>

          <Check
            checked={w.uncapped}
            disabled={w.activeProvider?.has_free_tier !== false}
            onChange={w.setUncapped}
            label={
              <span style={{ ...type.bodySm, color: color.dim }}>
                no request limit — stop when the agent finishes
              </span>
            }
          />
          <div style={{ ...type.caption, color: color.faint, margin: `4px 0 ${space[4]}px` }}>
            {w.activeProvider?.has_free_tier !== false
              ? 'unavailable on a free tier: one uncapped run would spend the daily quota'
              : w.uncapped
                ? 'bounded by the token ceiling and the 30-minute timeout instead. A run that ' +
                  'times out having produced a patch is still graded.'
                : 'measured: one agent spent all 100 requests and 3.0M input tokens without ' +
                  'ever deciding it was done'}
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: space[4] }}>
            <tbody>
              {(
                [
                  ['harnesses', w.harnesses.length],
                  ['models', w.models.length],
                  ['tasks', w.taskIds.length],
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
            <Metric
              label="model requests"
              value={w.requests}
              tone={w.overDailyCap ? 'warn' : 'pass'}
              sub={`free tier ≈ ${DAILY_FREE_REQUESTS}/day`}
            />
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
                This needs {w.requests} requests — more than a free-tier day. Runs that hit the
                limit are parked as rate-limited and resume automatically, so the matrix takes
                longer rather than failing.
              </Notice>
            </div>
          )}
        </Panel>

        <Panel label="Stacks entered">
          {w.harnesses.length === 0 || w.models.length === 0 ? (
            <div style={{ ...type.bodySm, color: color.faint }}>Nothing selected yet.</div>
          ) : (
            w.harnesses.flatMap((h) =>
              w.models.map((m) => (
                <div
                  key={`${h}-${m}`}
                  style={{
                    display: 'flex',
                    gap: space[2],
                    padding: `${space[2]}px 0`,
                    borderBottom: `1px solid ${color.lineSoft}`,
                    fontFamily: font.mono,
                    fontSize: 12.5,
                  }}
                >
                  <span style={{ color: color.text }}>{h}</span>
                  <span style={{ color: color.faint }}>×</span>
                  <span style={{ color: color.dim }}>{m.replace(/:free$/, '')}</span>
                </div>
              )),
            )
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
        {w.blockers.map((reason) => (
          <div key={reason} style={{ ...type.caption, color: color.warn, marginTop: space[2] }}>
            {reason}
          </div>
        ))}

        <Row style={{ marginTop: space[4] }}>
          <Button size="sm" variant="ghost" onClick={() => w.setStep(2)}>
            ← Back to stacks
          </Button>
        </Row>
      </div>
    </div>
  )
}
