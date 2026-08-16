import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { color, space } from '../design/tokens'
import { font, type } from '../design/typography'
import { UIStyles } from '../ui'
import { useStages } from '../stages'

/**
 * A reachability light. `title` is a real tooltip via the native attribute —
 * it needs no JS, works on keyboard focus, and is one less component to own.
 */
function Dot({ ok, title }: { ok: boolean | undefined; title: string }) {
  const c = ok === undefined ? color.faint : ok ? color.pass : color.fail
  return (
    <span
      title={title}
      aria-label={title}
      style={{
        width: 7,
        height: 7,
        borderRadius: '50%',
        background: c,
        boxShadow: `0 0 0 3px ${c}22`,
        flex: '0 0 auto',
      }}
    />
  )
}

/**
 * The workflow spine.
 *
 * A benchmark is a sequence — you cannot pick stacks before you have a repo,
 * or read results before anything has run — and the rail makes that sequence
 * the permanent frame rather than something you infer from the URL. Overview
 * sits above the six stages, separated by a rule, because it is a destination
 * rather than a step.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { stages } = useStages()

  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
  // Provider reachability is worth surfacing permanently: without it every run
  // fails, and the cause is not obvious from a run's error message.
  const provider = useQuery({
    queryKey: ['connection'],
    // Wrapped, not passed bare: api.connection takes an optional provider, and
    // react-query would otherwise hand it a QueryFunctionContext as that arg.
    queryFn: () => api.connection(),
    retry: false,
    staleTime: 60_000,
  })

  const onOverview = pathname === '/'

  return (
    <div
      className="aso-lab"
      style={{ display: 'grid', gridTemplateColumns: '236px minmax(0, 1fr)', minHeight: '100vh' }}
    >
      <UIStyles />

      <nav
        className="aso-rail"
        aria-label="Workflow"
        style={{
          borderRight: `1px solid ${color.line}`,
          background: color.surface,
          padding: `${space[6]}px 0`,
          position: 'sticky',
          top: 0,
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          gap: space[5],
        }}
      >
        <div style={{ padding: `0 ${space[5]}px` }}>
          <h1 style={{ ...type.subheading, fontSize: 19, fontWeight: 400, margin: 0 }}>
            Agent Stack Optimizer
          </h1>
          <p style={{ ...type.label, color: color.faint, margin: '2px 0 0' }}>local</p>
        </div>

        <div className="aso-stages" style={{ display: 'flex', flexDirection: 'column' }}>
          <Stage
            label="Overview"
            state={onOverview ? 'current' : 'available'}
            onClick={() => navigate('/')}
          />
          <div
            className="aso-rail-sep"
            style={{
              borderTop: `1px solid ${color.lineSoft}`,
              margin: `${space[2]}px ${space[5]}px`,
            }}
          />
          {stages.map((s) => (
            <Stage key={s.label} label={s.label} state={s.state} onClick={s.go} />
          ))}
        </div>

        <div style={{ marginTop: 'auto', padding: `0 ${space[5]}px`, display: 'grid', gap: space[3] }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: space[2], flexWrap: 'wrap' }}>
            <Dot
              ok={health.isSuccess ? true : health.isError ? false : undefined}
              title={
                health.isSuccess ? 'backend reachable' : 'backend unreachable — run make backend'
              }
            />
            <span style={{ ...type.caption, color: color.faint }}>api</span>
            <Dot
              ok={provider.data?.ok}
              title={
                provider.data?.ok
                  ? `OpenRouter reachable (${provider.data.latency_ms}ms)`
                  : 'OpenRouter unreachable — check OPENROUTER_API_KEY in .env'
              }
            />
            <span style={{ ...type.caption, color: color.faint }}>openrouter</span>
          </div>
          <p
            style={{
              fontFamily: font.mono,
              fontSize: 10,
              lineHeight: 1.6,
              color: color.faint,
              borderTop: `1px solid ${color.lineSoft}`,
              paddingTop: space[3],
              margin: 0,
            }}
          >
            Local Docker sandboxing suits trusted testing — it is not hardened isolation. Do not
            point this at repositories you would not run on your machine.
          </p>
        </div>
      </nav>

      <main
        className="aso-screens"
        style={{ padding: `${space[7]}px ${space[7]}px ${space[8]}px`, maxWidth: 1180, width: '100%' }}
      >
        {children}
      </main>
    </div>
  )
}

function Stage({
  label,
  state,
  onClick,
}: {
  label: string
  state: 'done' | 'current' | 'available' | 'locked'
  onClick?: () => void
}) {
  const locked = state === 'locked'
  const current = state === 'current'
  const dotBg = current ? color.live : state === 'done' ? color.pass : color.line
  return (
    <button
      type="button"
      className="aso-stage aso-inset-focus"
      aria-current={current ? 'page' : undefined}
      disabled={locked || !onClick}
      onClick={onClick}
      style={{
        display: 'grid',
        gridTemplateColumns: '26px 1fr',
        alignItems: 'center',
        gap: space[2],
        padding: `9px ${space[5]}px`,
        border: 0,
        width: '100%',
        textAlign: 'left',
        background: current ? color.raised : 'none',
        color: current ? color.text : state === 'done' ? color.dim : color.faint,
        fontFamily: font.sans,
        fontSize: 13,
        cursor: locked || !onClick ? 'default' : 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          marginLeft: 5,
          background: dotBg,
          boxShadow: current ? '0 0 0 3px rgba(76,201,232,.16)' : undefined,
        }}
      />
      {label}
    </button>
  )
}
