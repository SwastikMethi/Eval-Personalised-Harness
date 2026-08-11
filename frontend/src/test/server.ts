import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

/** Default happy-path handlers. Override per-test with server.use(...). */
export const handlers = [
  http.get('/api/v1/health', () => HttpResponse.json({ status: 'ok' })),
  http.get('/api/v1/experiments', () => HttpResponse.json([])),
  http.get('/api/v1/repositories', () => HttpResponse.json([])),
]

export const server = setupServer(...handlers)
export { http, HttpResponse }
