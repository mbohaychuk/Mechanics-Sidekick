import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/api/client', () => ({
  api: {
    getVehicle: vi.fn().mockResolvedValue({ id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' }),
    listDocuments: vi.fn().mockResolvedValue([
      { id: 7, vehicle_id: 1, file_name: 'manual.pdf', document_type: 'service_manual', processing_status: 'ready', uploaded_utc: 'x' },
    ]),
    listJobs: vi.fn().mockResolvedValue([
      { id: 3, vehicle_id: 1, title: 'Oil leak', description: null, status: 'open', created_utc: 'x' },
    ]),
    createJob: vi.fn(),
    getDocument: vi.fn(),
    uploadDocument: vi.fn(),
  },
}))

import VehicleDetailView from '@/views/VehicleDetailView.vue'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id', name: 'vehicle', component: VehicleDetailView },
    { path: '/jobs/:id/chat', name: 'chat', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}`)
  return router.isReady().then(() => mount(VehicleDetailView, { global: { plugins: [router] } }))
}

beforeEach(() => setActivePinia(createPinia()))

describe('VehicleDetailView', () => {
  it('shows the vehicle, its documents (with status), and its jobs', async () => {
    const wrapper = await mountAt('1')
    await flushPromises()
    expect(wrapper.text()).toContain('Audi')
    expect(wrapper.text()).toContain('manual.pdf')
    expect(wrapper.text().toLowerCase()).toContain('ready')
    expect(wrapper.text()).toContain('Oil leak')
  })
})
