import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { color, space } from '../../design/tokens'
import { measure, type } from '../../design/typography'
import { Button, Field, Metric, Notice, Panel, Row, Segmented, Status } from '../../ui'
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

  return (
    <Panel label="Repository">
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
        That is all that is needed to start. Languages, package managers and test commands are
        detected automatically, and a clean baseline runs in the background while you pick tasks —
        you can review and correct all of it on the last step.
      </p>

      <Button
        variant="primary"
        disabled={!w.pathOrUrl.trim() || w.addRepo.isPending}
        onClick={() => w.addRepo.mutate()}
      >
        {w.addRepo.isPending ? 'Analyzing…' : 'Analyze repository'}
      </Button>

      {w.analysis && (
        <div style={{ marginTop: space[5] }}>
          <Row gap={space[5]} style={{ alignItems: 'flex-start' }}>
            <Metric label="language" value={w.analysis.languages?.[0] ?? 'unknown'} />
            <Metric label="package manager" value={w.analysis.package_managers?.[0] ?? '—'} />
            <Metric
              label="size"
              value={(w.analysis.size_bytes / 1_000_000).toFixed(1)}
              unit="MB"
            />
            <Metric label="test locations" value={w.analysis.test_locations?.length ?? 0} />
          </Row>

          {/* A previous baseline means this repo has been benchmarked before —
              worth saying, because it avoids a needless container run. */}
          {previous.data && (
            <div style={{ marginTop: space[4] }}>
              <Status tone={previous.data.benchmarkable === false ? 'warn' : 'pass'}>
                previous baseline · {previous.data.test_case_count} tests
              </Status>
            </div>
          )}

          {w.analysis.supported === false && (
            <div style={{ marginTop: space[4] }}>
              <Notice tone="warn">
                This language or toolchain is not fully supported. You can continue, but detection
                will be thinner and you may have to enter the test command yourself.
              </Notice>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
