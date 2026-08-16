import { color, space } from '../../design/tokens'
import { font, type } from '../../design/typography'
import { Button, Check, Empty, Field, Notice, Panel, Row, Segmented } from '../../ui'
import type { Wizard } from './useWizard'

/**
 * Agent stacks — "which setups should compete?"
 *
 * A stack is one harness against one model, and the matrix is every pairing. The
 * count is shown on Review; this screen is only about what goes into it.
 */
export default function StepStacks({ w }: { w: Wizard }) {
  const stacks = w.harnesses.length * w.models.length

  return (
    <div>
      <Panel label="Harnesses">
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
            <code>:free</code> model is. Capabilities its listing omits show as <code>unknown</code>
            .
          </Notice>
        )}

        {w.showPaid && w.activeProvider?.has_free_tier !== false && (
          <Notice tone="warn">
            Paid models need OpenRouter credits, and spec §2 puts closed-source models out of scope
            — this tool benchmarks open-weight stacks. Open-weight-but-paid models (Kimi, GLM) are
            fine if you have credits.
          </Notice>
        )}

        {w.availableModels.isError && (
          <Notice tone="warn">Could not list models — check OPENROUTER_API_KEY in .env.</Notice>
        )}

        <div style={{ maxWidth: 420, marginBottom: space[3] }}>
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
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
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

      <Row style={{ justifyContent: 'space-between' }}>
        <span style={{ ...type.bodySm, color: color.dim }}>
          {stacks === 0
            ? 'pick at least one harness and one model'
            : `${stacks} stack${stacks === 1 ? '' : 's'} will compete`}
        </span>
        <Button variant="primary" disabled={stacks === 0} onClick={() => w.setStep(3)}>
          Continue
        </Button>
      </Row>
    </div>
  )
}
