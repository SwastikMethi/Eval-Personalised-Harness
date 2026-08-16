import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { color, space } from '../../design/tokens'
import { measure, type } from '../../design/typography'
import { Button, Field, Notice, Panel, ScreenTitle, Segmented, StepItem, Steps } from '../../ui'
import type { Wizard } from './useWizard'

/**
 * Repository — "can my repo be benchmarked?"
 *
 * One field and one button. Everything else is detected, and the last step lets
 * the user correct all of it, so asking for commands here would be asking for
 * work the tool can do itself.
 */
export default function StepRepository({ w }: { w: Wizard }) {
  // Reading the last baseline is free; re-running one costs a container.
  const previous = useQuery({
    queryKey: ['latest-baseline', w.repoId],
    queryFn: () => api.latestBaseline(w.repoId!),
    enabled: Boolean(w.repoId),
    retry: false,
  })

  const a = w.analysis
  return (
    <>
      <ScreenTitle
        ask="Can this repository be benchmarked?"
        title={a ? (w.pathOrUrl.replace(/\/+$/, '').split('/').pop() ?? 'Repository') : 'Point it at a repository'}
        lede="Languages, package managers and test commands are detected automatically, and a clean baseline runs in the background while you pick tasks."
      />

      {/* What the analyzer found, as a ladder rather than a row of figures:
          the question is whether this repo can be scored at all, and that is a
          sequence of things holding or not holding. */}
      {a && (
        <Panel label="Detected">
          <Steps>
            <StepItem state={a.languages?.length ? 'done' : 'failed'}>
              {a.languages?.length ? `${a.languages.join(', ')} · ${a.package_managers?.join(', ') || 'no package manager'}` : 'No language detected'}
            </StepItem>
            <StepItem state={a.test_locations?.length ? 'done' : 'failed'}>
              {a.test_locations?.length
                ? `Tests found in ${a.test_locations.join(', ')}`
                : 'No test directory found — comprehension tasks still work'}
            </StepItem>
            <StepItem state={a.commands?.test ? 'done' : 'failed'}>
              {a.commands?.test
                ? `Test command: ${a.commands.test}`
                : 'No test command detected — you can enter one on Review'}
            </StepItem>
            <StepItem
              state={
                w.runBaseline.isPending
                  ? 'doing'
                  : w.baselineBroken
                    ? 'failed'
                    : w.baseline
                      ? 'done'
                      : 'todo'
              }
            >
              {w.baselineLabel}
              {w.baseline ? ` · ${w.baseline.test_case_count} test cases` : ''}
            </StepItem>
            {previous.data && !w.baseline && (
              <StepItem state="done">
                Benchmarked before · {previous.data.test_case_count} test cases on the last baseline
              </StepItem>
            )}
          </Steps>

          {a.supported === false && (
            <div style={{ marginTop: space[4] }}>
              <Notice tone="warn">
                This language or toolchain is not fully supported. You can continue, but detection
                will be thinner and you may have to enter the test command yourself.
              </Notice>
            </div>
          )}

          <div style={{ marginTop: space[5] }}>
            <Button variant="primary" onClick={() => w.setStep(1)}>
              Continue
            </Button>
          </div>
        </Panel>
      )}

      <Panel label={a ? 'Analyse a different repository' : 'Repository'}>
      <div style={{ marginBottom: space[4] }}>
        <Segmented
          value={w.source}
          onChange={(v) => w.setSource(v)}
          options={[
            { value: 'local' as const, label: 'Local path' },
            { value: 'github' as const, label: 'Public GitHub URL' },
          ]}
        />
      </div>

      <div style={{ maxWidth: 620, marginBottom: space[3] }}>
        <Field
          label={w.source === 'local' ? 'path' : 'url'}
          value={w.pathOrUrl}
          onChange={w.setPathOrUrl}
          placeholder={
            w.source === 'local' ? '/Users/you/Projects/your-repo' : 'https://github.com/owner/repo'
          }
        />
      </div>

      <p style={{ ...type.bodySm, color: color.faint, maxWidth: measure, marginBottom: space[4] }}>
        A local path or a public GitHub URL. Everything else is detected, and you can review and
        correct all of it on the last step.
      </p>

      <Button
        variant="primary"
        disabled={!w.pathOrUrl.trim() || w.addRepo.isPending}
        onClick={() => w.addRepo.mutate()}
      >
        {w.addRepo.isPending ? 'Analyzing…' : 'Analyze repository'}
      </Button>
      </Panel>
    </>
  )
}
