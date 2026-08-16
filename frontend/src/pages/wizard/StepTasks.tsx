import { api } from '../../api'
import { color, space } from '../../design/tokens'
import { measure, font, type } from '../../design/typography'
import {
  Button,
  Check,
  Criterion,
  Empty,
  Field,
  Notice,
  Panel,
  Row,
  Rubric,
  ScreenTitle,
  Segmented,
  Status,
  TextArea,
} from '../../ui'
import type { Wizard } from './useWizard'

/**
 * Tasks — "what should the agents attempt?"
 *
 * Three modes, and they are not interchangeable: replaying a commit is the
 * strongest signal because the real tests shipped with it, while comprehension
 * is the only mode that works on a repo whose own tests cannot fail.
 */
export default function StepTasks({ w }: { w: Wizard }) {
  const proposedCount = w.proposed.length
  return (
    <>
      <ScreenTitle
        ask="What should the agents attempt?"
        title={
          proposedCount > 0 && w.taskMode === 'comprehension'
            ? `${proposedCount} question${proposedCount === 1 ? '' : 's'} proposed`
            : 'Choose the tasks'
        }
        lede="Replaying a commit is the strongest signal, because the real tests shipped with it. Comprehension is the only mode that works on a repo whose own tests cannot fail."
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.4fr) minmax(280px, 1fr)',
          gap: space[4],
          alignItems: 'start',
        }}
      >
      <Panel label="Task source">
        <div style={{ marginBottom: space[4] }}>
          <Segmented
            value={w.taskMode}
            onChange={(v) => w.setTaskMode(v)}
            options={[
              { value: 'commit' as const, label: 'Replay a commit' },
              { value: 'comprehension' as const, label: 'Understand the code' },
              { value: 'describe' as const, label: 'Describe a task' },
            ]}
          />
        </div>

        {w.taskMode === 'comprehension' && (
          <>
            <p style={{ ...type.bodySm, color: color.dim, maxWidth: measure, marginBottom: space[4] }}>
              Questions with a right answer — architecture, execution flow, or a plan for a change.
              Graded against a rubric written from this repository, so both harnesses are scored
              against the identical list. No test suite involved, which is why this works on a repo
              whose own tests cannot fail.
            </p>
            <Button
              disabled={w.proposeTasks.isPending}
              onClick={() => w.proposeTasks.mutate()}
              style={{ marginBottom: space[4] }}
            >
              {w.proposeTasks.isPending ? 'Reading the repository…' : 'Propose questions'}
            </Button>

            {w.proposed.map((t) => (
              <div
                key={t.id}
                style={{
                  marginBottom: space[4],
                  paddingBottom: space[4],
                  borderBottom: `1px solid ${color.lineSoft}`,
                }}
              >
                <Check
                  align="start"
                  checked={w.theoryTaskIds.includes(t.id)}
                  onChange={(on) =>
                    w.setTheoryTaskIds((prev) =>
                      on ? [...prev, t.id] : prev.filter((x) => x !== t.id),
                    )
                  }
                  label={
                    <span style={{ fontFamily: font.mono, fontSize: 13, color: color.text }}>
                      {t.title}
                    </span>
                  }
                  hint={`${t.category.replace('_', ' ')} · graded on ${t.rubric.length} criteria`}
                />
                {/* The rubric as a graded grid, not a paragraph. Depth is
                    colour-coded because six deep criteria grade very
                    differently from six structural ones — invisible as text. */}
                <div style={{ paddingLeft: 26, marginTop: space[2] }}>
                  <Rubric>
                    {t.rubric.map((c, i) => (
                      <Criterion key={i} depth={c.depth} evidence={c.evidence}>
                        {c.criterion}
                      </Criterion>
                    ))}
                  </Rubric>
                  {t.dropped.length > 0 && (
                    <div style={{ ...type.caption, color: color.warn, marginTop: space[2] }}>
                      {t.dropped.length} criterion/criteria dropped — cited paths that do not exist
                      in this repo
                    </div>
                  )}
                </div>
              </div>
            ))}
          </>
        )}

        {w.taskMode === 'commit' ? (
          <>
            <p style={{ ...type.bodySm, color: color.dim, maxWidth: measure, marginBottom: space[4] }}>
              Tick up to five. Each commit's <strong>parent</strong> becomes the starting state and
              the commit itself is the known answer — the agent only ever sees a fresh snapshot at
              the parent, with no remotes and no future history. This is the strongest signal
              available, because the real tests shipped with the commit.
            </p>

            {w.commits.isLoading && <Empty>Reading the git log…</Empty>}
            {/* Without this a failed clone renders as "no commits", which is
                what made a perfectly good GitHub repo look empty. */}
            {w.commits.isError && (
              <Notice tone="fail">
                Could not read commits:{' '}
                {w.commits.error instanceof Error ? w.commits.error.message : 'unknown error'}
              </Notice>
            )}
            {w.askAi.isPending && (
              <div style={{ ...type.bodySm, color: color.dim, marginBottom: space[3] }}>
                reading the README and the code to shortlist commits worth benchmarking…
              </div>
            )}

            {w.nominated.length > 0 && (
              <Row style={{ justifyContent: 'space-between', marginBottom: space[3] }}>
                <span style={{ ...type.label, color: color.faint }}>
                  {w.usingShortlist
                    ? `shortlisted · ${w.nominated.length}`
                    : `all commits · ${w.commitList.length}`}
                </span>
                <Button size="sm" variant="ghost" onClick={() => w.setShowAllCommits((v) => !v)}>
                  {w.usingShortlist ? 'show all commits' : 'show shortlist'}
                </Button>
              </Row>
            )}

            <div style={{ maxHeight: 380, overflowY: 'auto' }}>
              {w.commitList.map((c) => (
                <Check
                  key={c.sha}
                  align="start"
                  disabled={w.pickCommit.isPending}
                  checked={w.selectedShas.includes(c.sha)}
                  onChange={(on) => {
                    if (on) w.pickCommit.mutate(c.sha)
                    else w.setSelectedShas((p) => p.filter((s) => s !== c.sha))
                  }}
                  label={
                    <span style={{ fontFamily: font.mono, fontSize: 12.5, color: color.text }}>
                      {(c.subject ?? '').slice(0, 72)}
                    </span>
                  }
                  hint={
                    <>
                      {c.sha.slice(0, 8)}
                      {c.author ? ` · ${c.author}` : ''}
                      {c.date ? ` · ${c.date.slice(0, 10)}` : ''}
                      {'why' in c && c.why && (
                        <div
                          style={{
                            ...type.bodySm,
                            fontSize: 12.5,
                            color: color.dim,
                            marginTop: 2,
                            maxWidth: '54ch',
                          }}
                        >
                          {c.why}
                        </div>
                      )}
                    </>
                  }
                />
              ))}
            </div>

            {!w.commits.isLoading && !w.commits.isError && (w.commits.data ?? []).length === 0 && (
              <Empty>No commits with a parent found — describe a task instead.</Empty>
            )}
          </>
        ) : w.taskMode === 'describe' ? (
          <div style={{ display: 'grid', gap: space[4], maxWidth: 620 }}>
            <Field label="title" mono={false} value={w.title} onChange={w.setTitle} />
            <TextArea
              label="prompt"
              value={w.prompt}
              onChange={w.setPrompt}
              placeholder="Describe the change precisely. The agent sees only this and the repository."
            />
            <div>
              <Button
                disabled={!w.title.trim() || !w.prompt.trim() || w.describeTask.isPending}
                onClick={() => w.describeTask.mutate()}
              >
                Add task
              </Button>
            </div>
          </div>
        ) : null}

        <hr
          style={{
            border: 0,
            borderTop: `1px solid ${color.line}`,
            margin: `${space[5]}px 0 ${space[4]}px`,
          }}
        />

        <div style={{ ...type.label, color: color.faint, marginBottom: space[2] }}>
          selected · {w.taskIds.length}
        </div>
        {w.taskIds.length === 0 ? (
          <Empty>Nothing selected yet.</Empty>
        ) : (
          <Row gap={space[2]}>
            {w.selectedShas.map((s) => (
              <Status key={s}>{s.slice(0, 8)}</Status>
            ))}
            {w.theoryTaskIds.map((id) => (
              <Status key={id}>question</Status>
            ))}
            {w.describedTaskIds.map((id) => (
              <Status key={id}>described</Status>
            ))}
          </Row>
        )}

        <div style={{ marginTop: space[4] }}>
          <Button variant="primary" disabled={w.taskIds.length === 0} onClick={() => w.setStep(2)}>
            Continue
          </Button>
        </div>
      </Panel>

      <Panel label="Hidden test candidates">
        <p style={{ ...type.bodySm, color: color.dim, marginBottom: space[4] }}>
          Extracted from the target commit and run only <em>after</em> the agent stops.
          Low-confidence candidates start unapproved — nothing runs without your say-so.
        </p>

        <Button
          size="sm"
          disabled={w.selectedShas.length === 0 || w.prepare.isPending}
          onClick={() => w.prepare.mutate()}
          style={{ width: '100%', marginBottom: space[2] }}
        >
          {w.prepare.isPending ? 'Preparing & verifying…' : 'Prepare & verify tests'}
        </Button>
        <div style={{ ...type.caption, color: color.faint, marginBottom: space[4] }}>
          {w.prepare.isPending
            ? 'running the suite at the parent and the fix — minutes, not seconds'
            : 'repairs the test environment, and writes a test when the commit shipped none'}
        </div>

        {w.prepare.data?.reports.map((r) => (
          <Notice
            key={r.task_id}
            tone={r.generated_test && !r.generated_test.verified ? 'warn' : 'info'}
          >
            prompt written by{' '}
            {r.prompt_source === 'model' ? r.provenance.model : 'the commit message'}
            {r.prompt_source === 'commit-message' &&
              ' (model output was unusable or leaked the fix)'}
            {r.generated_test && (
              <div style={{ marginTop: 4 }}>
                {r.generated_test.verified
                  ? `generated ${r.generated_test.relpath} — proven to fail before the fix and pass after it`
                  : `no usable test after ${r.generated_test.attempts} attempt(s): ${r.generated_test.reject_reason}`}
              </div>
            )}
          </Notice>
        ))}

        {w.hidden.length === 0 ? (
          <Empty>None yet. Tick a commit, then prepare &amp; verify.</Empty>
        ) : (
          w.hidden.map((h) => (
            <div
              key={h.id}
              style={{
                marginBottom: space[3],
                paddingBottom: space[3],
                borderBottom: `1px solid ${color.lineSoft}`,
              }}
            >
              <Check
                checked={h.approved === true}
                onChange={async (on) => {
                  await api.approveHiddenTest(h.id, on)
                  w.setHidden((prev) =>
                    prev.map((x) => (x.id === h.id ? { ...x, approved: on } : x)),
                  )
                }}
                label={
                  <span style={{ fontFamily: font.mono, fontSize: 12.5, color: color.text }}>
                    {h.relpath}
                  </span>
                }
                hint={`${h.change_type} · confidence ${h.confidence}${
                  h.reject_reason ? ` · ${h.reject_reason}` : ''
                }`}
              />
            </div>
          ))
        )}
      </Panel>
    </div>
    </>
  )
}
