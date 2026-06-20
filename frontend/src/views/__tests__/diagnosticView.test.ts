import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import type { DiagnosticStreamEvent } from '@/api/diagnosticStream'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'initOptions', 'autoresize', 'manualUpdate'], template: '<div class="v-chart-stub" />' },
}))

const handlers: { current: ((e: DiagnosticStreamEvent) => void) | null } = { current: null }
vi.mock('@/api/diagnosticStream', () => ({
  streamDiagnostic: vi.fn(async (_v: number, _p: string, onEvent: (e: DiagnosticStreamEvent) => void, signal?: AbortSignal) => {
    handlers.current = onEvent
    await new Promise<void>((resolve) => { if (signal) signal.addEventListener('abort', () => resolve()) })
  }),
}))

import DiagnosticSessionView from '@/views/DiagnosticSessionView.vue'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id/diagnostic', name: 'diagnostic', component: DiagnosticSessionView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}/diagnostic`)
  return router.isReady().then(() => mount(DiagnosticSessionView, { global: { plugins: [router] } }))
}

beforeEach(() => { setActivePinia(createPinia()); handlers.current = null })

describe('DiagnosticSessionView', () => {
  it('starts a session and renders steps, commentary, vitals, and the report', async () => {
    const wrapper = await mountAt('1')
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()

    handlers.current!({
      type: 'session', diagnostic_session_id: 3, live_session_id: 9,
      protocol: [{ id: 'idle_baseline', label: 'Idle baseline', instruction: 'Let it idle' }],
    })
    handlers.current!({ type: 'step', index: 0, total: 1, id: 'idle_baseline', label: 'Idle baseline', instruction: 'Let it idle', state: 'active', adhoc: false })
    handlers.current!({ type: 'sample', seq: 1, t: 0, hz: 1, values: { RPM: { value: 700, unit: 'rpm' } } })
    handlers.current!({ type: 'commentary', text: 'Idle looks steady.', t: 0 })
    await flushPromises()

    expect(wrapper.text()).toContain('Idle baseline')
    expect(wrapper.text()).toContain('Idle looks steady.')
    expect(wrapper.text()).toContain('RPM')
    expect(wrapper.findAll('.v-chart-stub').length).toBeGreaterThanOrEqual(1)

    handlers.current!({ type: 'report', overall_status: 'good', summary: 'All clear.', findings: [] })
    handlers.current!({ type: 'done' })
    await flushPromises()
    expect(wrapper.text()).toContain('All clear.')
  })
})
