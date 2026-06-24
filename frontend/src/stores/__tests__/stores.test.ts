import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    listVehicles: vi.fn(),
    createVehicle: vi.fn(),
    getScannerStatus: vi.fn(),
    getConfig: vi.fn(),
  },
}))

import { api } from '@/api/client'
import { useVehiclesStore } from '@/stores/vehicles'
import { useScannerStore } from '@/stores/scanner'

beforeEach(() => setActivePinia(createPinia()))

describe('vehicles store', () => {
  it('loads vehicles and exposes the selected one', async () => {
    ;(api.listVehicles as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' },
    ])
    const store = useVehiclesStore()
    await store.load()
    expect(store.vehicles).toHaveLength(1)
    store.select(1)
    expect(store.selected?.make).toBe('Audi')
  })

  it('prepends a created vehicle', async () => {
    ;(api.createVehicle as ReturnType<typeof vi.fn>).mockResolvedValue(
      { id: 2, year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L', vin: null, notes: null, created_utc: 'x' },
    )
    const store = useVehiclesStore()
    const v = await store.create({ year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L' })
    expect(v.id).toBe(2)
    expect(store.vehicles[0].make).toBe('Subaru')
  })
})

describe('scanner store', () => {
  it('refreshes status', async () => {
    ;(api.getScannerStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      { available: true, scanner_reachable: false, detail: 'OBD server up; scanner not reachable.' },
    )
    const store = useScannerStore()
    await store.refresh()
    expect(store.status?.available).toBe(true)
    expect(store.status?.scanner_reachable).toBe(false)
  })

  it('polls status on an interval until stopped (so the badge auto-detects a plug-in)', async () => {
    vi.useFakeTimers()
    const mock = api.getScannerStatus as ReturnType<typeof vi.fn>
    mock.mockResolvedValue({ available: true, scanner_reachable: false, detail: 'x' })
    mock.mockClear()
    const store = useScannerStore()

    store.startPolling(1000)
    await vi.advanceTimersByTimeAsync(0)       // immediate first probe
    expect(mock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mock).toHaveBeenCalledTimes(3)

    store.stopPolling()
    await vi.advanceTimersByTimeAsync(3000)
    expect(mock).toHaveBeenCalledTimes(3)      // no further probes after stop
    vi.useRealTimers()
  })
})
