import { useQuery } from '@tanstack/react-query'
import { Alert, Box, Button, Grid, Typography } from '@mui/material'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Empty, Mono, PageTitle, Panel } from '../components/primitives'
import { C, fonts } from '../theme'

export default function Dashboard() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
  const experiments = useQuery({ queryKey: ['experiments'], queryFn: api.experiments })
  const repositories = useQuery({ queryKey: ['repositories'], queryFn: api.repositories })

  return (
    <Box>
      <PageTitle
        title="Which stack is best for your repo?"
        sub="Benchmark coding-agent harnesses against open-weight models on tasks from your own repository, and get quality, reliability and efficiency recommendations."
        action={
          <Button component={Link} to="/new" variant="contained" size="large">
            New run
          </Button>
        }
      />

      {health.isError && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          Backend unreachable — run <code>make backend</code>.
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Panel label="Recent experiments">
            {experiments.data?.length ? (
              experiments.data
                .slice()
                .reverse()
                .map((e) => (
                  <Box
                    key={e.id}
                    component={Link}
                    to={`/experiments/${e.id}`}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      py: 1.1,
                      px: 1,
                      mx: -1,
                      textDecoration: 'none',
                      borderBottom: `1px solid ${C.lineSoft}`,
                      '&:hover': { backgroundColor: C.surfaceHi },
                    }}
                  >
                    <Mono color={C.text}>{e.name}</Mono>
                    <Mono size="0.7rem" color={e.status === 'running' ? C.live : C.faint}>
                      {e.status}
                    </Mono>
                  </Box>
                ))
            ) : (
              <Empty>No experiments yet — start one with “New run”.</Empty>
            )}
          </Panel>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Panel label="Repositories">
            {repositories.data?.length ? (
              repositories.data.map((r) => (
                <Box key={r.id} sx={{ py: 0.9, borderBottom: `1px solid ${C.lineSoft}` }}>
                  <Mono color={C.text}>{r.name}</Mono>
                  <Typography
                    sx={{
                      fontFamily: fonts.mono,
                      fontSize: '0.66rem',
                      color: C.faint,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.source} · {r.path_or_url}
                  </Typography>
                </Box>
              ))
            ) : (
              <Empty>No repositories registered.</Empty>
            )}
          </Panel>
        </Grid>
      </Grid>
    </Box>
  )
}
