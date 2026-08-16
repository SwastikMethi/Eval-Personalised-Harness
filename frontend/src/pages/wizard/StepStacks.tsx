import { useState } from 'react'
import { color, space } from '../../design/tokens'
import { font, type } from '../../design/typography'
import {
  AddCard,
  Button,
  Check,
  Dialog,
  Empty,
  Field,
  Notice,
  Panel,
  Row,
  ScreenTitle,
  Segmented,
  StackCard,
  Status,
} from '../../ui'
import type { Wizard } from './useWizard'

/**
 * Which setups should compete?
 *
 * A stack is one harness against one model, and the matrix is every pairing. It
 * used to be two checkbox lists, which meant the thing being compared — the
 * pairing — was never actually shown; you had to multiply it in your head.
 */
export default function StepStacks({ w }: { w: Wizard }) {
  const [picking, setPicking] = useState(false)

  const stacks = w.harnesses.flatMap((h) => w.models.map((m) => ({ harness: h, model: m })))

  return (
    <div>
      <ScreenTitle
        ask="Which setups should compete?"
        title={
          stacks.length === 0
            ? 'Choose the stacks'
            : `${stacks.length} agent stack${stacks.length === 1 ? '' : 's'}`
        }
        lede="Every harness is paired with every model you pick. Each pairing runs the same tasks against the same snapshot, so the only thing that differs is the stack."
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
          gap: space[3],
          marginBottom: space[4],
        }}
      >
        {stacks.map((s) => (
          <StackCard
            key={`${s.harness}-${s.model}`}
            selected
            harness={s.harness}
            model={s.model.replace(/:free$/, '')}
            status={<span style={{ ...type.caption, color: color.faint }}>×</span>}
            footer={
              <span style={{ ...type.caption, color: color.faint }}>
                {w.reps} rep{w.reps === 1 ? '' : 's'} · {w.taskIds.length} task
                {w.taskIds.length === 1 ? '' : 's'}
              </span>
            }
          />
        ))}
        <AddCard onClick={() => setPicking(true)}>
          {stacks.length === 0 ? '+ Choose harnesses and models' : '+ Add agent stack'}
        </AddCard>
      </div>

      {stacks.length === 0 && (
        <Notice tone="info">
          Nothing selected yet. A comparison needs at least one harness and one model.
        </Notice>
      )}

      <Row style={{ justifyContent: 'space-between' }}>
        <span style={{ ...type.bodySm, color: color.dim }}>
          {stacks.length === 0
            ? 'pick at least one harness and one model'
            : `${w.harnesses.length} harness${w.harnesses.length === 1 ? '' : 'es'} × ${
                w.models.length
              } model${w.models.length === 1 ? '' : 's'}`}
        </span>
        <Button variant="primary" disabled={stacks.length === 0} onClick={() => w.setStep(3)}>
          Continue
        </Button>
      </Row>

      <Dialog
        open={picking}
        title="Harnesses and models"
        onClose={() => setPicking(false)}
        footer={
          <Button variant="primary" onClick={() => setPicking(false)}>
            Done
          </Button>
        }
      >
        <Panel label="Harnesses" style={{ marginBottom: space[4] }}>
          {(w.availableHarnesses.data ?? []).length === 0 ? (
            <Empty>No harnesses registered.</Empty>
          ) : (
            (w.availableHarnesses.data ?? []).map((h) => (
              <Check
                key={h.name}
                checked={w.harnesses.includes(h.name)}
                onChange={() => w.toggle(w.harnesses, h.name, w.setHarnesses)}
                label={
                  <Row gap={space[2]}>
                    <span style={{ fontFamily: font.mono, fontSize: 13, color: color.text }}>
                      {h.name}
                    </span>
                    <span style={{ ...type.caption, color: color.faint }}>
                      {h.sandboxed ? 'sandboxed' : 'in-process'}
                    </span>
                  </Row>
                }
              />
            ))
          )}
        </Panel>

        <Panel
          label={`Models · ${w.sortedModels.length}`}
          action={
            <Check
              checked={w.showPaid}
              onChange={(on) => {
                w.setShowPaid(on)
                w.setModels([])
              }}
              label={<span style={{ ...type.bodySm, color: color.dim }}>include paid</span>}
            />
          }
          style={{ marginBottom: 0 }}
        >
          <div style={{ marginBottom: space[3] }}>
            <Segmented
              value={w.provider}
              onChange={(v) => {
                w.setProvider(v)
                w.setModels([]) // ids are provider-specific
              }}
              options={(w.providers.data ?? []).map((p) => ({
                value: p.name,
                label: `${p.name}${p.configured ? '' : ' · no key'}`,
                disabled: !p.configured,
              }))}
            />
          </div>

          {w.activeProvider?.has_free_tier === false && (
            <Notice tone="info">
              {w.provider} bills credits rather than offering a free per-token tier, so cost is
              recorded as $0.00 but is <strong>not</strong> verified the way an OpenRouter{' '}
              <code>:free</code> model is. Capabilities its listing omits show as{' '}
              <code>unknown</code>.
            </Notice>
          )}

          {w.showPaid && w.activeProvider?.has_free_tier !== false && (
            <Notice tone="warn">
              Paid models need OpenRouter credits, and spec §2 puts closed-source models out of
              scope — this tool benchmarks open-weight stacks. Open-weight-but-paid models (Kimi,
              GLM) are fine if you have credits.
            </Notice>
          )}

          {w.availableModels.isError && (
            <Notice tone="warn">Could not list models — check OPENROUTER_API_KEY in .env.</Notice>
          )}

          <div style={{ marginBottom: space[3] }}>
            <Field
              label="filter"
              value={w.modelFilter}
              onChange={w.setModelFilter}
              placeholder="filter by name…"
            />
          </div>

          {w.availableModels.isLoading ? (
            <Empty>Listing models…</Empty>
          ) : (
            <div style={{ maxHeight: 280, overflowY: 'auto' }}>
              {w.sortedModels.map((m) => (
                <Check
                  key={m.model_id}
                  checked={w.models.includes(m.model_id)}
                  onChange={() => w.toggle(w.models, m.model_id, w.setModels)}
                  label={
                    <span style={{ fontFamily: font.mono, fontSize: 12.5, color: color.text }}>
                      {m.model_id}
                    </span>
                  }
                  hint={
                    <>
                      {m.context_length ? `${(m.context_length / 1000).toFixed(0)}k ctx` : ''}
                      {m.is_free ? ' · free' : ' · paid'}
                      {/* null is UNKNOWN, not unsupported — the provider simply
                          does not report it. */}
                      {m.supports_tools === null
                        ? ' · tools unknown'
                        : m.supports_tools
                          ? ' · tools'
                          : ' · no tools'}
                    </>
                  }
                />
              ))}
            </div>
          )}
        </Panel>

        {stacks.length > 0 && (
          <div style={{ marginTop: space[4] }}>
            <Status tone="live">
              {stacks.length} stack{stacks.length === 1 ? '' : 's'}
            </Status>
          </div>
        )}
      </Dialog>
    </div>
  )
}
