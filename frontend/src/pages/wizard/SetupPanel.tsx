import { color, space } from '../../design/tokens'
import { measure, font, type } from '../../design/typography'
import { Button, Field, Label, Metric, Notice, Output, Panel, Row } from '../../ui'
import { OPTIONAL_COMMANDS, type Wizard } from './useWizard'

/**
 * The commands, who chose them, and the baseline that proves they work.
 *
 * Collapsed by default and opens itself only when something genuinely needs the
 * user — a repo with a detected test command and a passing baseline should not
 * make anyone read this.
 */
export default function SetupPanel({ w }: { w: Wizard }) {
  const { strategy, suggestion, baseline } = w

  // Every selected task is graded by rubric, so there is nothing for a test
  // command or a baseline to contribute. Saying so is better than leaving a
  // panel that reads "baseline not run" as though something were missing.
  if (w.theoryOnly) {
    return (
      <Panel label="Setup">
        <p style={{ ...type.bodySm, color: color.dim, maxWidth: measure }}>
          Comprehension tasks are graded against a rubric written from this repository — no test
          suite, no patch and no dependency install. Nothing needs to be configured here, and no
          baseline is run.
        </p>
      </Panel>
    )
  }

  return (
    <Panel>
      <button
        type="button"
        className="aso-focusable"
        onClick={() => w.setSetupOpen(!w.setupOpen)}
        aria-expanded={w.setupOpen}
        style={{
          display: 'flex',
          width: '100%',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: space[4],
          background: 'none',
          border: 0,
          padding: 0,
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <span>
          <Label>setup</Label>
          <span
            style={{
              display: 'block',
              fontFamily: font.mono,
              fontSize: 12.5,
              color: w.needsAttention ? color.warn : color.dim,
            }}
          >
            {[
              w.analysis?.languages?.[0] ?? 'unknown',
              w.framework || 'no framework',
              w.baselineLabel,
            ].join(' · ')}
          </span>
        </span>
        <span style={{ ...type.caption, color: color.live }}>
          {w.setupOpen ? 'hide' : 'review'}
        </span>
      </button>

      {/* Unmounted rather than hidden: collapsed fields left in the DOM stay
          tab-focusable while invisible. */}
      {w.setupOpen && (
        <div style={{ marginTop: space[4], borderTop: `1px solid ${color.line}`, paddingTop: space[4] }}>
          <Label>commands</Label>

          <Row gap={space[2]} style={{ margin: `${space[3]}px 0` }}>
            <Button
              size="sm"
              variant="primary"
              disabled={w.decideStrategy.isPending || !w.repoId}
              onClick={() => w.decideStrategy.mutate()}
            >
              {w.decideStrategy.isPending ? 'Analysing and verifying…' : 'Analyse & verify'}
            </Button>
            <Button
              size="sm"
              disabled={w.askAi.isPending || !w.repoId}
              onClick={() => w.askAi.mutate(true)}
            >
              {w.askAi.isPending ? 'Analyzing repo…' : 'Suggest with AI'}
            </Button>
          </Row>

          {/* This is the only feature that transmits repo content anywhere —
              say so before it is pressed, not after. */}
          <div style={{ ...type.caption, color: color.faint, maxWidth: measure }}>
            both send file names, README, manifests and CI config to the model provider · secrets
            (.env, keys) are never included · “Analyse &amp; verify” also RUNS the commands in a
            container to prove they produce a score
          </div>

          {strategy && (
            <div
              style={{
                marginTop: space[3],
                padding: space[3],
                border: `1px solid ${strategy.scoreable ? color.faint : color.warn}`,
                borderRadius: 6,
              }}
            >
              <div
                style={{
                  fontFamily: font.mono,
                  fontSize: 12.5,
                  color: strategy.scoreable ? color.text : color.warn,
                }}
              >
                {strategy.strategy.replace('_', ' ')}
                {strategy.scoreable ? '' : ' — this repo cannot be scored'}
              </div>
              <div style={{ ...type.caption, color: color.dim, marginTop: 4 }}>
                {strategy.meaning}
              </div>
              {/* The ladder, so a verdict can be argued with rather than
                  merely accepted. */}
              {strategy.attempts.map((a) => (
                <div
                  key={`${a.rung}-${a.strategy}`}
                  style={{
                    ...type.caption,
                    color: a.ok ? color.text : color.faint,
                    marginTop: 3,
                  }}
                >
                  {a.ok ? '✓' : '✗'} rung {a.rung} {a.strategy.replace('_', ' ')} — {a.reason}
                </div>
              ))}
              <div style={{ ...type.caption, color: color.faint, marginTop: space[2] }}>
                decided by {strategy.provenance.provider}/{strategy.provenance.model} · verified by
                running the commands, not by asking
              </div>
            </div>
          )}

          {suggestion && (
            <div style={{ ...type.caption, color: color.dim, marginTop: space[2] }}>
              suggested by {suggestion.model_id} · confidence {suggestion.confidence} · read{' '}
              {suggestion.files_read.length} file{suggestion.files_read.length === 1 ? '' : 's'} ·
              review and save below
            </div>
          )}

          <div style={{ display: 'grid', gap: space[3], margin: `${space[4]}px 0` }}>
            <Field
              label="test"
              value={w.commands.test ?? ''}
              onChange={(v) => w.setCommands({ ...w.commands, test: v })}
              hint={
                suggestion?.rationale?.test
                  ? `AI: ${suggestion.rationale.test}`
                  : w.testCommand
                    ? 'how the evaluator runs your tests'
                    : 'required — without it there is no correctness signal'
              }
            />
            {OPTIONAL_COMMANDS.map((field) => (
              <Field
                key={field}
                label={`${field} (optional)`}
                value={w.commands[field] ?? ''}
                onChange={(v) => w.setCommands({ ...w.commands, [field]: v })}
                hint={
                  suggestion?.rationale?.[field]
                    ? `AI: ${suggestion.rationale[field]}`
                    : 'leave blank to skip'
                }
              />
            ))}
            <Field
              label="test framework"
              value={w.framework}
              onChange={w.setFramework}
              hint="pytest, vitest, jest… decides how test output is parsed"
            />
          </div>

          <Button
            size="sm"
            onClick={() => w.saveCommands.mutate()}
            disabled={w.saveCommands.isPending}
          >
            Save commands
          </Button>

          {suggestion && suggestion.commits.length > 0 && (
            <div style={{ marginTop: space[5] }}>
              <Label>suggested commits to benchmark</Label>
              <p style={{ ...type.bodySm, color: color.dim, margin: `${space[2]}px 0 ${space[3]}px` }}>
                Commits that fix behaviour and touch tests grade best. Add them here without going
                back a step.
              </p>
              {suggestion.commits.map((c) => {
                const added = w.selectedShas.includes(c.sha)
                return (
                  <div
                    key={c.sha}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      justifyContent: 'space-between',
                      gap: space[3],
                      padding: `${space[3]}px 0`,
                      borderBottom: `1px solid ${color.lineSoft}`,
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontFamily: font.mono, fontSize: 12.5, color: color.text }}>
                        {c.subject || c.sha.slice(0, 8)}
                      </div>
                      <div style={{ ...type.caption, color: color.faint }}>
                        {c.sha.slice(0, 8)} · {c.why}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      disabled={added || w.pickCommit.isPending}
                      onClick={() => w.pickCommit.mutate(c.sha)}
                    >
                      {added ? 'added' : 'add as task'}
                    </Button>
                  </div>
                )
              })}
            </div>
          )}

          <div style={{ marginTop: space[5] }}>
            <Label>baseline</Label>
            <p
              style={{
                ...type.bodySm,
                color: color.dim,
                maxWidth: measure,
                margin: `${space[2]}px 0 ${space[3]}px`,
              }}
            >
              Runs your commands on a clean snapshot before any agent touches the repo, so failures
              that already existed are never blamed on an agent.
            </p>

            {baseline && (
              <Row gap={space[5]} style={{ marginBottom: space[3], alignItems: 'flex-start' }}>
                {Object.entries(baseline.steps).map(([name, s]) => (
                  <Metric
                    key={name}
                    label={name}
                    value={s.exit_code === 0 ? 'pass' : `exit ${s.exit_code}`}
                    tone={s.exit_code === 0 ? 'pass' : 'warn'}
                  />
                ))}
                <Metric label="baseline tests" value={baseline.test_case_count} />
              </Row>
            )}

            {w.baselineStale && (
              <Notice tone="info">
                Commands changed since this baseline ran — re-run it so regressions are measured
                against the right starting point.
              </Notice>
            )}
            {w.baselineBroken && (
              <Notice tone="fail">
                Baseline could not establish a signal — install or build failed, or tests could not
                be collected. Fix the commands above and re-run.
              </Notice>
            )}

            {/* The actual failure output. "exit 2" alone is undiagnosable —
                and when the cause is a tool the sandbox lacks, the backend
                names it, because a raw Docker build log does not. */}
            {baseline &&
              Object.entries(baseline.steps)
                .filter(([, s]) => s.exit_code !== 0 && (s.output || s.diagnosis))
                .map(([name, s]) => (
                  <div key={name} style={{ marginBottom: space[3] }}>
                    <Label>{name} output</Label>
                    {s.diagnosis && <Notice tone="warn">{s.diagnosis}</Notice>}
                    {s.output && (
                      <div style={{ marginTop: space[2] }}>
                        <Output>{s.output}</Output>
                      </div>
                    )}
                  </div>
                ))}

            {baseline?.warn && !w.baselineBroken && (
              <Notice tone="warn">
                Baseline is partially failing. You can proceed — those failures are excluded from
                regression counting.
              </Notice>
            )}

            <Button
              size="sm"
              disabled={w.runBaseline.isPending || !w.repoId}
              onClick={() => w.runBaseline.mutate(w.repoId!)}
            >
              {w.runBaseline.isPending ? 'Running…' : 'Re-run baseline'}
            </Button>
          </div>
        </div>
      )}
    </Panel>
  )
}
