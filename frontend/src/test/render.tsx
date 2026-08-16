import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

/**
 * Screens use router links and react-query — wrap both. Styling needs no
 * provider now that the design tokens are plain values rather than a theme.
 * retry:false so error states assert immediately instead of after backoff.
 *
 * `pattern` matters for any screen that reads useParams: rendering the element
 * directly under MemoryRouter leaves it outside every Route, so useParams
 * returns {} and the screen silently behaves as if it has no id.
 */
export function renderScreen(ui: ReactElement, route = '/', pattern?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        {pattern ? (
          <Routes>
            <Route path={pattern} element={ui} />
          </Routes>
        ) : (
          ui
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
