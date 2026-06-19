import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, ApiError } from '@/api/client'

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('lists vehicles via GET /api/vehicles', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([{ id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' }]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const vehicles = await api.listVehicles()

    expect(fetchMock).toHaveBeenCalledWith('/api/vehicles', expect.objectContaining({ method: 'GET' }))
    expect(vehicles[0].make).toBe('Audi')
  })

  it('creates a vehicle via POST with a JSON body', async () => {
    const created = { id: 2, year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L', vin: null, notes: null, created_utc: 'x' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(created, 201))
    vi.stubGlobal('fetch', fetchMock)

    const vehicle = await api.createVehicle({ year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/vehicles')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toMatchObject({ make: 'Subaru' })
    expect(vehicle.id).toBe(2)
  })

  it('uploads a document as multipart to the 202 endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: 5, vehicle_id: 1, file_name: 'm.pdf', document_type: 'service_manual', processing_status: 'pending', uploaded_utc: 'x' }, 202),
    )
    vi.stubGlobal('fetch', fetchMock)

    const file = new File(['%PDF'], 'm.pdf', { type: 'application/pdf' })
    const doc = await api.uploadDocument(1, file)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/vehicles/1/documents')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect(doc.processing_status).toBe('pending')
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Vehicle 999 not found' }, 404)))
    await expect(api.getVehicle(999)).rejects.toBeInstanceOf(ApiError)
  })
})
