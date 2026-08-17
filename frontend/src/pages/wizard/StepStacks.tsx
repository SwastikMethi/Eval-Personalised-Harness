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
} from '../../ui'
import { stackKey, type Wizard } from './useWizard'

/**
 * Which setups should compete?
 *
 * A stack is one harness against one model on one provider, and it used to be
 * impossible to say that: two checkbox lists were multiplied into every
 * pairing, on a single provider for the whole matrix. The picker still crosses
 * what you tick in one visit — a sweep should not cost more clicks than before
 * — but visits accumulate, so an arbitrary set of pairs is finally expressible.
 */
export default function StepStacks({ w }: { w: Wizard }) {
  const [picking, setPicking] = useState(false)

  const close = () => {
    setPicking(false)
    w.setDraftHarnesses([])
    w.setDraftModels([])
  }
  const confirm = () => {
    w.addDraftStacks()
    setPicking(false)
  }

  const draftCount = w.draftStacks.length
  const mixedProviders = new Set(w.stacks.map((s) => s.provider)).size > 1

  return (
    <div>
      <ScreenTitle
        ask="Which setups should compete?"
        title={
          w.stacks.length === 0
            ? 'Choose the stacks'
            : `${w.stacks.length} agent stack${w.stacks.length === 1 ? '' : 's'}`
        }
        lede="Each stack is one harness against one model. They run the same tasks against the same snapshot, so the stack is the only thing that differs — and they need not share a provider."
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
          gap: space[3],
          marginBottom: space[4],
        }}
      >
        {w.stacks.map((s) => {
          const key = stackKey(s)
          return (
            <StackCard
              key={key}
              selected
              harness={s.harness}
              model={s.model_id.replace(/:free$/, '')}
              // A separate button, not the card itself: StackCard's body is a
              // <button> when clickable, and nesting buttons is invalid and
              // breaks the keyboard order.
              status={
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => w.removeStack(key)}
                  title={`Remove ${s.harness} × ${s.model_id}`}
                >
                  remove
                </Button>
              }
              footer={
                <>
                  <span style={{ ...type.caption, color: color.faint }}>{s.provider}</span>
                  <span style={{ ...type.caption, color: color.faint }}>
                    {w.reps} rep{w.reps === 1 ? '' : 's'} · {w.taskIds.length} task
                    {w.taskIds.length === 1 ? '' : 's'}
                  </span>
                </>
              }
            />
          )
        })}
        <AddCard onClick={() => setPicking(true)}>
          {w.stacks.length === 0 ? '+ Choose harnesses and models' : '+ Add agent stack'}
        </AddCard>
      </div>

      {w.stacks.length === 0 && (
        <Notice tone="info">
          Nothing selected yet. Add one harness and one model for a single stack, or tick several
          of each to add every pairing between them at once.
        </Notice>
      )}

      {mixedProviders && (
        <Notice tone="info">
          This matrix spans more than one provider. That is a fair comparison of stacks, but cost
          and latency are not comparable across providers — only correctness is.
        </Notice>
      )}

      <Row style={{ justifyContent: 'space-between' }}>
        <span style={{ ...type.bodySm, color: color.dim }}>
          {w.stacks.length === 0
            ? 'pick at least one harness and one model'
            : `${w.stacks.length} stack${w.stacks.length === 1 ? '' : 's'} will compete`}
        </span>
        <Button variant="primary" disabled={w.stacks.length === 0} onClick={() => w.setStep(3)}>
          Continue
        </Button>
      </Row>

      <Dialog
        open={picking}
        title="Add agent stacks"
        onClose={close}
        footer={
          <>
            <Button variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button variant="primary" disabled={draftCount === 0} onClick={confirm}>
              {draftCount === 0
                ? 'Add stacks'
                : `Add ${draftCount} stack${draftCount === 1 ? '' : 's'}`}
            </Button>
          </>
        }
      >
        <Panel label="Harnesses" style={{ marginBottom: space[4] }}>
          {(w.availableHarnesses.data ?? []).length === 0 ? (
            <Empty>No harnesses registered.</Empty>
          ) : (
            (w.availableHarnesses.data ?? []).map((h) => (
              <Check
                key={h.name}
                checked={w.draftHarnesses.includes(h.name)}
                onChange={() => w.toggle(w.draftHarnesses, h.name, w.setDraftHarnesses)}
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
                w.setDraftModels([])
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
                // Model ids are provider-specific, so a half-made selection
                // would silently point at the wrong catalogue.
                w.setDraftModels([])
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
            <div style={{ maxHeight: 260, overflowY: 'auto' }}>
              {w.sortedModels.map((m) => (
                <Check
                  key={m.model_id}
                  checked={w.draftModels.includes(m.model_id)}
                  onChange={() => w.toggle(w.draftModels, m.model_id, w.setDraftModels)}
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

        {/* Say what this visit will contribute, so a multi-tick never
            multiplies into more stacks than the reader expected. */}
        <div style={{ ...type.caption, color: color.faint, marginTop: space[4] }}>
          {draftCount === 0
            ? 'tick at least one harness and one model'
            : `${w.draftHarnesses.length} × ${w.draftModels.length} = ${draftCount} stack${
                draftCount === 1 ? '' : 's'
              } on ${w.provider}, added to the ${w.stacks.length} already chosen`}
        </div>
      </Dialog>
    </div>
  )
}
