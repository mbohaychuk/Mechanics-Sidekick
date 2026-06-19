import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/api/client', () => ({
  api: {
    listVehicles: vi.fn().mockResolvedValue([]),
    getScannerStatus: vi.fn().mockResolvedValue({ available: false, scanner_reachable: false, detail: 'x' }),
  },
}))

import VehiclesView from '@/views/VehiclesView.vue'

describe('scaffold', () => {
  it('renders the vehicles view', () => {
    setActivePinia(createPinia())
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: VehiclesView }],
    })
    const wrapper = mount(VehiclesView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('Fleet')
  })
})
