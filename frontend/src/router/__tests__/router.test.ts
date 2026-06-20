import { describe, it, expect } from 'vitest'
import { router } from '@/router'

describe('router', () => {
  it('resolves unknown paths to a not-found route', () => {
    const resolved = router.resolve('/totally/made/up/path')
    expect(resolved.name).toBe('not-found')
  })

  it('still resolves known deep routes', () => {
    expect(router.resolve('/vehicles/3/diagnostic').name).toBe('diagnostic')
  })
})
