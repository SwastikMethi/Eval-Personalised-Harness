import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  AppBar,
  Box,
  Card,
  CardContent,
  Chip,
  Container,
  Grid,
  Toolbar,
  Typography,
} from '@mui/material'
import { api } from '../api'

export default function Dashboard() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
  const experiments = useQuery({ queryKey: ['experiments'], queryFn: api.experiments })
  const repositories = useQuery({ queryKey: ['repositories'], queryFn: api.repositories })

  return (
    <Box>
      <AppBar position="static" elevation={0}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Agent Stack Optimizer
          </Typography>
          <Chip
            label={health.isSuccess ? 'backend: ok' : 'backend: offline'}
            color={health.isSuccess ? 'success' : 'error'}
            size="small"
          />
        </Toolbar>
      </AppBar>
      <Container sx={{ mt: 4 }}>
        {health.isError && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Backend unreachable — run <code>make backend</code>.
          </Alert>
        )}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="overline">Recent repositories</Typography>
                {repositories.data?.length ? (
                  repositories.data.map((r) => (
                    <Typography key={r.id} variant="body2">
                      {r.name} <Chip label={r.source} size="small" />
                    </Typography>
                  ))
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    No repositories yet.
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="overline">Recent experiments</Typography>
                {experiments.data?.length ? (
                  experiments.data.map((e) => (
                    <Typography key={e.id} variant="body2">
                      <a href={`/experiments/${e.id}`}>{e.name}</a>{' '}
                      <Chip label={e.status} size="small" />
                    </Typography>
                  ))
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    No experiments yet.
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>
    </Box>
  )
}
