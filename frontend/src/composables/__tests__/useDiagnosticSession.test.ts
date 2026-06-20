import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import type { DiagnosticStreamEvent } from '@/api/diagnosticStream'

const handlers: { current: ((e: DiagnosticStreamEvent) => void) | null } = { current: null }

vi.mock('@/api/diagnosticStream', () => ({
  streamDiagnostic: vi.fn(async (_v: number, _p: string, onEvent: (e: DiagnosticStreamEvent) => void, signal?: AbortSignal) => {
    handlers.current = onEvent
    await new Promise<void>((resolve) => { if (signal) signal.addEventListener('abort', () => resolve()) })
  }),
}))

import { useDiagnosticSession } from '@/composables/useDiagnosticSession'

beforeEach(() => { handlers.current = null })

describe('useDiagnosticSession', () => {
  it('tracks protocol steps, samples, commentary, anomalies, and the report', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()

    handlers.current!({
      type: 'session', diagnostic_session_id: 3, live_session_id: 9,
      protocol: [{ id: 'idle_baseline', label: 'Idle', instruction: 'idle' },
                 { id: 'rev_2500', label: 'Rev', instruction: 'rev' }],
    })
    expect(d.status.value).toBe('running')
    expect(d.steps.value.map((s) => s.state)).toEqual(['pending', 'pending'])

    handlers.current!({ type: 'step', index: 0, total: 2, id: 'idle_baseline', label: 'Idle', instruction: 'idle', state: 'active', adhoc: false })
    expect(d.steps.value[0].state).toBe('active')
    expect(d.currentIndex.value).toBe(0)

    handlers.current!({ type: 'sample', seq: 1, t: 0, values: { RPM: { value: 700, unit: 'rpm' } } })
    handlers.current!({ type: 'sample', seq: 2, t: 1000, values: { RPM: { value: 720, unit: 'rpm' } } })
    expect(d.latest.RPM!.value).toBe(720)
    expect(d.series.RPM).toEqual([[0, 700], [1000, 720]])

    handlers.current!({ type: 'step', index: 0, total: 2, id: 'idle_baseline', label: 'Idle', instruction: 'idle', state: 'done', adhoc: false })
    expect(d.steps.value[0].state).toBe('done')

    handlers.current!({ type: 'commentary', text: 'Idle steady.', t: 1000 })
    expect(d.commentary.value[0].text).toBe('Idle steady.')

    handlers.current!({ type: 'anomaly', system: 'fuel', severity: 'warn', pid: 'LONG_FUEL_TRIM_1', detail: '+14% lean' })
    expect(d.anomalies.value[0].system).toBe('fuel')

    handlers.current!({ type: 'report', overall_status: 'fair', summary: 'ok', findings: [] })
    expect(d.report.value?.overall_status).toBe('fair')

    handlers.current!({ type: 'done' })
    expect(d.status.value).toBe('complete')
  })

  it('goes to error on an error event', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()
    handlers.current!({ type: 'error', detail: 'no scanner' })
    expect(d.status.value).toBe('error')
    expect(d.detail.value).toContain('scanner')
  })
})
