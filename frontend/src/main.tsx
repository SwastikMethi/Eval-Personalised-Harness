import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import AppShell from './components/AppShell'
import Dashboard from './pages/Dashboard'
import Live from './pages/Live'
import RunDetail from './pages/RunDetail'
import Wizard from './pages/Wizard'
import { StageProvider } from './stages'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <StageProvider>
          <AppShell>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/new" element={<Wizard />} />
              <Route path="/experiments/:id" element={<Live />} />
              <Route path="/runs/:id" element={<RunDetail />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AppShell>
        </StageProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
