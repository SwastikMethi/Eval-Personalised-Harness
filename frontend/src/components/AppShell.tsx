import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api'
import { color, radius, space } from '../design/tokens'
import { font, type } from '../design/typography'
import { UIStyles } from '../ui'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/new', label: 'New run' },
]

/**
 * A reachability light. `title` is a real tooltip via the native attribute
 * rather than MUI's — it needs no JS, works on keyboard focus, and one less
 * component is one less thing to port.
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

export default function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
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

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <UIStyles />

      <header
        style={{
          borderBottom: `1px solid ${color.line}`,
          background: 'rgba(10,11,13,.86)',
          backdropFilter: 'blur(8px)',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <div
          style={{
            maxWidth: 1400,
            margin: '0 auto',
            padding: `${space[3]}px ${space[5]}px`,
            display: 'flex',
            alignItems: 'center',
            gap: space[5],
          }}
        >
          <Link to="/" style={{ display: 'flex', alignItems: 'baseline', gap: space[2] }}>
            <span style={{ ...type.subheading, color: color.text }}>Agent Stack Optimizer</span>
            <span style={{ ...type.label, color: color.faint }}>local</span>
          </Link>

          <nav style={{ display: 'flex', gap: space[1] }}>
            {NAV.map((item) => {
              const active = item.to === '/' ? pathname === '/' : pathname.startsWith(item.to)
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className="aso-focusable"
                  aria-current={active ? 'page' : undefined}
                  style={{
                    fontFamily: font.sans,
                    fontSize: 13,
                    fontWeight: 500,
                    padding: `5px ${space[3]}px`,
                    borderRadius: radius.sm,
                    color: active ? color.text : color.dim,
                    background: active ? color.raised : 'transparent',
                  }}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>

          <div style={{ flexGrow: 1 }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: space[3] }}>
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
        </div>
      </header>

      <main
        style={{
          maxWidth: 1400,
          width: '100%',
          margin: '0 auto',
          padding: `${space[6]}px ${space[5]}px`,
          flexGrow: 1,
        }}
      >
        {children}
      </main>

      <footer
        style={{
          borderTop: `1px solid ${color.lineSoft}`,
          padding: `${space[4]}px ${space[5]}px`,
          marginTop: space[6],
        }}
      >
        <div style={{ maxWidth: 1400, margin: '0 auto' }}>
          <p style={{ ...type.caption, color: color.faint }}>
            Local Docker sandboxing is appropriate for trusted testing — it is not hardened
            multi-tenant isolation. Do not point this at repositories you would not run on your
            machine.
          </p>
        </div>
      </footer>
    </div>
  )
}
