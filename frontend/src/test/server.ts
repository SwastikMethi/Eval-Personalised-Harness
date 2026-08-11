import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

/** Default happy-path handlers. Override per-test with server.use(...). */
export const handlers = [
  http.get('/api/v1/health', () => HttpResponse.json({ status: 'ok' })),
  http.get('/api/v1/experiments', () => HttpResponse.json([])),
  http.get('/api/v1/repositories', () => HttpResponse.json([])),
  http.get('/api/v1/harnesses', () =>
    HttpResponse.json([
      { name: 'mini-swe-agent', sandboxed: true },
      { name: 'smolagents', sandboxed: true },
      { name: 'fake', sandboxed: false },
    ]),
  ),
  http.get('/api/v1/providers/openrouter/connection', () =>
    HttpResponse.json({ ok: true, latency_ms: 42 }),
  ),
  http.get('/api/v1/providers/openrouter/models', () =>
    HttpResponse.json([
      {
        provider: 'openrouter',
        model_id: 'openai/gpt-oss-20b:free',
        display_name: 'gpt-oss-20b',
        context_length: 131072,
        supports_tools: true,
        is_free: true,
      },
      {
        provider: 'openrouter',
        model_id: 'cohere/north-mini-code:free',
        display_name: 'north-mini-code',
        context_length: 256000,
        supports_tools: true,
        is_free: true,
      },
    ]),
  ),
]

export const server = setupServer(...handlers)
export { http, HttpResponse }
