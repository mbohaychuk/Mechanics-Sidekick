import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => ({
  api: {
    listLiveSessions: vi.fn().mockResolvedValue([
      { id: 3, vehicle_id: 1, status: 'ended', started_utc: '2026-06-19T10:00:00Z', ended_utc: '2026-06-19T10:01:00Z', achieved_hz: 0.9, sample_count: 2, pids: ['RPM'] },
    ]),
    getLiveSession: vi.fn().mockResolvedValue({
      session: { id: 3, vehicle_id: 1, status: 'ended', pids: ['RPM'], sample_count: 2 },
      samples: [
        { seq: 1, t: 0, values: { RPM: { value: 800, unit: 'rpm' } } },
        { seq: 2, t: 1000, values: { RPM: { value: 820, unit: 'rpm' } } },
      ],
    }),
  },
}))

import SessionHistory from '@/components/SessionHistory.vue'

beforeEach(() => vi.clearAllMocks())

describe('SessionHistory', () => {
  it('lists sessions and emits replay series for a chosen session', async () => {
    const wrapper = mount(SessionHistory, { props: { vehicleId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('#3')          // session id shown
    expect(wrapper.text().toLowerCase()).toContain('ended')

    await wrapper.find('button[data-session="3"]').trigger('click')
    await flushPromises()

    const emitted = wrapper.emitted('replay')
    expect(emitted).toBeTruthy()
    const series = emitted![0][0] as { name: string; points: [number, number][] }[]
    expect(series[0].name).toBe('RPM')
    expect(series[0].points).toEqual([[0, 800], [1000, 820]])
  })
})
