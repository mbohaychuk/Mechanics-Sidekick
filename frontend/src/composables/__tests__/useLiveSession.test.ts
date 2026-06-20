import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import type { LiveEvent } from '@/api/types'

const handlers: { current: ((e: LiveEvent) => void) | null } = { current: null }

vi.mock('@/api/liveStream', () => ({
  streamLive: vi.fn(async (_vid: number, _pids: string[], onEvent: (e: LiveEvent) => void, signal?: AbortSignal) => {
    handlers.current = onEvent
    // resolve when aborted (mirrors a real stop)
    await new Promise<void>((resolve) => {
      if (signal) signal.addEventListener('abort', () => resolve())
    })
  }),
}))

import { useLiveSession } from '@/composables/useLiveSession'

beforeEach(() => { handlers.current = null })

describe('useLiveSession', () => {
  it('streams samples into latest + capped series and tracks state', async () => {
    const s = useLiveSession(1)
    s.start(['RPM', 'SPEED'])
    await flushPromises()

    handlers.current!({ type: 'session', session_id: 7, target_hz: 1 })
    expect(s.status.value).toBe('streaming')
    expect(s.sessionId.value).toBe(7)

    handlers.current!({ type: 'sample', seq: 1, t: 0, hz: 0.9, values: { RPM: { value: 800, unit: 'rpm' }, SPEED: null } })
    handlers.current!({ type: 'sample', seq: 2, t: 1000, hz: 0.95, values: { RPM: { value: 820, unit: 'rpm' }, SPEED: null } })

    expect(s.achievedHz.value).toBe(0.95)
    expect(s.latest.RPM!.value).toBe(820)
    expect(s.latest.SPEED).toBeNull()
    expect(s.series.RPM).toEqual([[0, 800], [1000, 820]])
    expect(s.series.SPEED ?? []).toEqual([])  // null values are not charted

    s.stop()
    await flushPromises()
    expect(s.status.value).toBe('idle')
  })

  it('surfaces vin_mismatch and disconnected', async () => {
    const s = useLiveSession(1)
    s.start(['RPM'])
    await flushPromises()
    handlers.current!({ type: 'vin_mismatch', detail: 'scanner VIN differs' })
    expect(s.vinMismatch.value).toContain('VIN')
    handlers.current!({ type: 'disconnected', detail: 'adapter dropped' })
    expect(s.status.value).toBe('error')
    expect(s.detail.value).toContain('adapter')
  })

  it('enforces WINDOW=120 rolling cap on series', async () => {
    const s = useLiveSession(1)
    s.start(['RPM'])
    await flushPromises()

    handlers.current!({ type: 'session', session_id: 1, target_hz: 1 })

    // Feed 121 samples with increasing values
    for (let seq = 1; seq <= 121; seq++) {
      handlers.current!({
        type: 'sample',
        seq,
        t: seq * 100,
        hz: 1,
        values: { RPM: { value: seq, unit: 'rpm' } },
      })
    }

    expect(s.series.RPM.length).toBe(120)
    // First remaining point should have value 2 (first point was dropped)
    expect(s.series.RPM[0][1]).toBe(2)
    // Last point should have value 121
    expect(s.series.RPM[119][1]).toBe(121)
  })
})
