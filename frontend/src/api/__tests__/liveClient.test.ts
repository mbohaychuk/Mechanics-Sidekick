import { describe, it, expect, vi, afterEach } from 'vitest'
import { api } from '@/api/client'

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body), text: () => Promise.resolve('') } as Response
}
afterEach(() => vi.restoreAllMocks())

describe('live api client', () => {
  it('gets supported pids', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ available: true, curated: ['RPM'], supported: [{ pid: '0C', name: 'RPM', description: 'Engine RPM' }] }))
    vi.stubGlobal('fetch', fetchMock)
    const res = await api.getSupportedPids(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/vehicles/1/supported-pids', expect.objectContaining({ method: 'GET' }))
    expect(res.curated).toContain('RPM')
    expect(res.supported[0].name).toBe('RPM')
  })

  it('lists and gets sessions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{ id: 3, vehicle_id: 1, status: 'ended', started_utc: 'x', ended_utc: 'y', achieved_hz: 0.9, sample_count: 12, pids: ['RPM'] }])))
    const list = await api.listLiveSessions(1)
    expect(list[0].sample_count).toBe(12)

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ session: { id: 3, vehicle_id: 1, status: 'ended', pids: ['RPM'], sample_count: 2 }, samples: [{ seq: 1, t: 0, values: { RPM: { value: 800, unit: 'rpm' } } }] })))
    const detail = await api.getLiveSession(3)
    expect(detail.samples[0].values.RPM!.value).toBe(800)
  })
})
