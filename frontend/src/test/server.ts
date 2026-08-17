import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

/** The default OpenRouter listing, exported so a test can serve both at once. */
export const OPENROUTER_MODELS = [
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
]

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
  http.get('/api/v1/providers', () =>
    HttpResponse.json([
      { name: 'openrouter', configured: true, has_free_tier: true },
      { name: 'nvidia', configured: true, has_free_tier: false },
    ]),
  ),
  http.get('/api/v1/providers/:provider/connection', () =>
    HttpResponse.json({ ok: true, latency_ms: 42 }),
  ),
  http.get('/api/v1/providers/:provider/models', () => HttpResponse.json(OPENROUTER_MODELS)),
]

/** A NIM-shaped listing: capabilities absent, so unknown rather than false. */
export const NIM_MODELS = [
  {
    provider: 'nvidia',
    model_id: 'deepseek-ai/deepseek-coder-6.7b-instruct',
    display_name: 'deepseek-ai/deepseek-coder-6.7b-instruct',
    context_length: null,
    supports_tools: null,
    is_free: false,
  },
]

export const server = setupServer(...handlers)
export { http, HttpResponse }
