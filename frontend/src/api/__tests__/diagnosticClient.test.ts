import { describe, it, expect, vi, afterEach } from 'vitest'
import { api } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('diagnostic client methods', () => {
  it('lists reports and gets one session', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [{ id: 3, overall_status: 'fair' }] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ session: { id: 3 }, report: { summary: 'ok' } }) } as Response)
    vi.stubGlobal('fetch', fetchMock)

    const list = await api.listDiagnosticReports(1)
    expect(list[0].overall_status).toBe('fair')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/vehicles/1/diagnostic-reports')

    const detail = await api.getDiagnosticSession(3)
    expect(detail.report?.summary).toBe('ok')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/diagnostic-sessions/3')
  })
})
