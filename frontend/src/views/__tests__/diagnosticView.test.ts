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

vi.mock('@/api/client', () => ({
  api: { listDiagnosticReports: vi.fn(), getDiagnosticSession: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import DiagnosticSessionView from '@/views/DiagnosticSessionView.vue'
import { useScannerStore } from '@/stores/scanner'
import { api } from '@/api/client'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id/diagnostic', name: 'diagnostic', component: DiagnosticSessionView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}/diagnostic`)
  return router.isReady().then(() => mount(DiagnosticSessionView, { global: { plugins: [router] } }))
}

beforeEach(() => {
  setActivePinia(createPinia())
  // The Start button is gated on a reachable scanner; mark it connected for these tests.
  useScannerStore().status = { available: true, scanner_reachable: true, detail: 'Scanner connected.' }
  handlers.current = null
  ;(api.listDiagnosticReports as ReturnType<typeof vi.fn>).mockResolvedValue([])
  ;(api.getDiagnosticSession as ReturnType<typeof vi.fn>).mockReset()
})

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
    handlers.current!({ type: 'anomaly', system: 'fuel', severity: 'warn', pid: 'LONG_FUEL_TRIM_1', detail: '+14% lean' })
    await flushPromises()

    expect(wrapper.text()).toContain('Idle baseline')
    expect(wrapper.text()).toContain('Idle looks steady.')
    expect(wrapper.text()).toContain('RPM')
    expect(wrapper.findAll('.v-chart-stub').length).toBe(1)
    expect(wrapper.text()).toContain('+14% lean')

    handlers.current!({ type: 'report', overall_status: 'good', summary: 'All clear.', findings: [] })
    handlers.current!({ type: 'done' })
    await flushPromises()
    expect(wrapper.text()).toContain('All clear.')
  })

  it('loads past diagnostic reports on mount and opens one on click', async () => {
    (api.listDiagnosticReports as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 7, status: 'complete', protocol_name: 'default', started_utc: '2026-06-01T10:00:00',
        ended_utc: '2026-06-01T10:05:00', overall_status: 'fair', summary: 'Minor fuel trim drift.' },
    ]);
    (api.getDiagnosticSession as ReturnType<typeof vi.fn>).mockResolvedValue({
      session: { id: 7, vehicle_id: 1, status: 'complete', protocol_name: 'default',
        overall_status: 'fair', started_utc: '2026-06-01T10:00:00', ended_utc: '2026-06-01T10:05:00' },
      report: { overall_status: 'fair', summary: 'Minor fuel trim drift detected on bank 1.', findings: [] },
    })

    const wrapper = await mountAt('1')
    await flushPromises()

    expect(api.listDiagnosticReports).toHaveBeenCalledWith(1)
    expect(wrapper.text()).toContain('Minor fuel trim drift.')

    await wrapper.find('[data-test="past-report-7"]').trigger('click')
    await flushPromises()

    expect(api.getDiagnosticSession).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('Minor fuel trim drift detected on bank 1.')
  })

  it('refreshes the past-reports list when a live run completes', async () => {
    (api.listDiagnosticReports as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([]) // on mount: none yet
      .mockResolvedValueOnce([
        { id: 9, status: 'complete', protocol_name: 'default', started_utc: '2026-06-20T09:00:00',
          ended_utc: '2026-06-20T09:05:00', overall_status: 'good', summary: 'Freshly generated report.' },
      ]) // after the run completes

    const wrapper = await mountAt('1')
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()

    handlers.current!({ type: 'report', overall_status: 'good', summary: 'Live.', findings: [] })
    handlers.current!({ type: 'done' })
    await flushPromises()

    expect(wrapper.text()).toContain('Freshly generated report.')
  })
})
