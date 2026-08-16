import { useQuery } from '@tanstack/react-query'
import { Box, Container, Tooltip, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api'
import { C, fonts } from '../theme'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/new', label: 'New run' },
]

function Dot({ ok, title }: { ok: boolean | undefined; title: string }) {
  const color = ok === undefined ? C.faint : ok ? C.pass : C.fail
  return (
    <Tooltip title={title}>
      <Box
        sx={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          backgroundColor: color,
          boxShadow: `0 0 0 3px ${color}22`,
          flex: '0 0 auto',
        }}
      />
    </Tooltip>
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
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Box
        component="header"
        sx={{
          borderBottom: `1px solid ${C.line}`,
          backgroundColor: 'rgba(10,11,13,0.86)',
          backdropFilter: 'blur(8px)',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <Container maxWidth="xl" sx={{ display: 'flex', alignItems: 'center', gap: 4, py: 1.5 }}>
          <Box
            component={Link}
            to="/"
            sx={{ textDecoration: 'none', display: 'flex', alignItems: 'baseline', gap: 1 }}
          >
            <Typography sx={{ fontFamily: fonts.display, fontSize: '1.3rem', color: C.text }}>
              Agent Stack Optimizer
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: '0.6rem',
                letterSpacing: '0.18em',
                color: C.faint,
                textTransform: 'uppercase',
              }}
            >
              local
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', gap: 0.5, ml: 1 }}>
            {NAV.map((item) => {
              const active = item.to === '/' ? pathname === '/' : pathname.startsWith(item.to)
              return (
                <Typography
                  key={item.to}
                  component={Link}
                  to={item.to}
                  sx={{
                    textDecoration: 'none',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    px: 1.5,
                    py: 0.5,
                    borderRadius: '3px',
                    color: active ? C.text : C.dim,
                    backgroundColor: active ? C.surfaceHi : 'transparent',
                    '&:hover': { color: C.text },
                  }}
                >
                  {item.label}
                </Typography>
              )
            })}
          </Box>

          <Box sx={{ flexGrow: 1 }} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Dot
              ok={health.isSuccess ? true : health.isError ? false : undefined}
              title={health.isSuccess ? 'backend reachable' : 'backend unreachable — run make backend'}
            />
            <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.68rem', color: C.faint }}>
              api
            </Typography>
            <Dot
              ok={provider.data?.ok}
              title={
                provider.data?.ok
                  ? `OpenRouter reachable (${provider.data.latency_ms}ms)`
                  : 'OpenRouter unreachable — check OPENROUTER_API_KEY in .env'
              }
            />
            <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.68rem', color: C.faint }}>
              openrouter
            </Typography>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="xl" sx={{ py: 4, flexGrow: 1 }}>
        {children}
      </Container>

      <Box
        component="footer"
        sx={{ borderTop: `1px solid ${C.lineSoft}`, py: 2, mt: 4 }}
      >
        <Container maxWidth="xl">
          <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.66rem', color: C.faint }}>
            Local Docker sandboxing is appropriate for trusted testing — it is not hardened
            multi-tenant isolation. Do not point this at repositories you would not run on your
            machine.
          </Typography>
        </Container>
      </Box>
    </Box>
  )
}
