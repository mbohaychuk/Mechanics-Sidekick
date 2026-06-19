import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'initOptions', 'autoresize', 'manualUpdate'], template: '<div class="v-chart-stub" />' },
}))
vi.mock('@/api/client', () => ({
  api: {
    getSupportedPids: vi.fn().mockResolvedValue({
      available: true, curated: ['RPM', 'SPEED'],
      supported: [{ pid: '0C', name: 'RPM', description: 'Engine RPM' }, { pid: '0D', name: 'SPEED', description: 'Speed' }],
    }),
  },
}))

import LiveView from '@/views/LiveView.vue'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id/live', name: 'live', component: LiveView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}/live`)
  return router.isReady().then(() => mount(LiveView, { global: { plugins: [router] } }))
}

beforeEach(() => setActivePinia(createPinia()))

describe('LiveView', () => {
  it('lists the default (curated ∩ supported) PIDs and a start control', async () => {
    const wrapper = await mountAt('1')
    await flushPromises()
    expect(wrapper.text()).toContain('RPM')
    expect(wrapper.text()).toContain('SPEED')
    expect(wrapper.text().toLowerCase()).toContain('start')
    // a sparkline per PID row is rendered (stubbed chart)
    expect(wrapper.findAll('.v-chart-stub').length).toBeGreaterThanOrEqual(2)
  })
})
