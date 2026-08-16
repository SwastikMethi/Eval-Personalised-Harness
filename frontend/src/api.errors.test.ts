import { describe, expect, it } from 'vitest'

import { describeDetail } from './api'

/** Clicking Start showed "422 Unprocessable Entity" and nothing else. The
 *  reason — which model, and the provider's own explanation — was in the
 *  response body, but the client only read `detail` when it was a string and
 *  dropped everything structured. */
describe('describeDetail', () => {
  it('passes a plain string through', () => {
    expect(describeDetail('repository uses git submodules')).toBe(
      'repository uses git submodules',
    )
  })

  it('names the unusable model and the provider reason', () => {
    const detail = {
      message: 'these model(s) cannot be used and no runs were created',
      unusable: [
        {
          combination: 'nvidia/deepseek-ai/deepseek-coder-6.7b-instruct',
          reason: 'provider rejected request (404): Not found for account',
        },
      ],
    }
    const text = describeDetail(detail) ?? ''
    expect(text).toContain('deepseek-coder-6.7b-instruct')
    expect(text).toContain('Not found for account')
  })

  it('reads FastAPI validation errors, which arrive as a list', () => {
    const detail = [{ loc: ['body', 'repository_id'], msg: 'field required', type: 'missing' }]
    expect(describeDetail(detail)).toBe('body.repository_id: field required')
  })

  it('never returns an empty string for an unexpected shape', () => {
    expect(describeDetail({ weird: true })).toBeTruthy()
    expect(describeDetail(null)).toBeNull()
    expect(describeDetail(undefined)).toBeNull()
  })
})
