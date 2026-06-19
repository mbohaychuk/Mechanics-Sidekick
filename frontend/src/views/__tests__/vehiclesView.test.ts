import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/api/client', () => ({
  api: {
    listVehicles: vi.fn().mockResolvedValue([
      { id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' },
    ]),
    createVehicle: vi.fn(),
    getScannerStatus: vi.fn().mockResolvedValue({ available: false, scanner_reachable: false, detail: 'x' }),
  },
}))

import VehiclesView from '@/views/VehiclesView.vue'

function routerStub() {
  return createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: VehiclesView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
}

beforeEach(() => setActivePinia(createPinia()))

describe('VehiclesView', () => {
  it('renders the vehicles from the store', async () => {
    const router = routerStub()
    const wrapper = mount(VehiclesView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Audi')
    expect(wrapper.text()).toContain('A8')
  })
})
