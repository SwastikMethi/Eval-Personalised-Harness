import { describe, expect, it } from 'vitest'
import { api } from './api'
import { http, HttpResponse, server } from './test/server'

describe('api client', () => {
  it('returns parsed json on success', async () => {
    await expect(api.health()).resolves.toEqual({ status: 'ok' })
  })

  it('throws on non-2xx rather than returning a broken body', async () => {
    server.use(
      http.get('/api/v1/experiments', () => new HttpResponse(null, { status: 500 })),
    )
    // A silent undefined here would render as an empty dashboard that looks
    // healthy — the error must surface so the UI can show it.
    await expect(api.experiments()).rejects.toThrow(/500/)
  })

  it('requests the versioned prefix for experiment detail', async () => {
    let seen = ''
    server.use(
      http.get('/api/v1/experiments/:id', ({ request, params }) => {
        seen = new URL(request.url).pathname
        return HttpResponse.json({
          id: params.id,
          name: 'x',
          status: 'running',
          runs: { total: 0, by_state: {} },
        })
      }),
    )
    await api.experiment('abc')
    expect(seen).toBe('/api/v1/experiments/abc')
  })
})
