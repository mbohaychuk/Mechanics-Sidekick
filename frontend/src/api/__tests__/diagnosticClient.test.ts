import { describe, it, expect, vi, afterEach } from 'vitest'
import { api } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('diagnostic client methods', () => {
  it('lists diagnostic reports — correct URL and shape', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: 3, overall_status: 'fair' }],
    } as Response)
    vi.stubGlobal('fetch', fetchMock)

    const list = await api.listDiagnosticReports(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/vehicles/1/diagnostic-reports')
    expect(list[0].overall_status).toBe('fair')
  })

  it('gets a diagnostic session — correct URL and shape', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ session: { id: 3 }, report: { summary: 'ok' } }),
    } as Response)
    vi.stubGlobal('fetch', fetchMock)

    const detail = await api.getDiagnosticSession(3)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/diagnostic-sessions/3')
    expect(detail.report?.summary).toBe('ok')
  })
})
