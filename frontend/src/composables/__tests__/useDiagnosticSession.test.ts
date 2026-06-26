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

    handlers.current!({ type: 'sample', seq: 1, t: 0, hz: 1, values: { RPM: { value: 700, unit: 'rpm' } } })
    handlers.current!({ type: 'sample', seq: 2, t: 1000, hz: 1, values: { RPM: { value: 720, unit: 'rpm' } } })
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

  it('tracks live step_progress and clears it at each step boundary', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()
    handlers.current!({
      type: 'session', diagnostic_session_id: 1, live_session_id: 1,
      protocol: [{ id: 'rev_2500', label: 'Rev', instruction: 'hold 2500' }],
    })
    handlers.current!({ type: 'step', index: 0, total: 1, id: 'rev_2500', label: 'Rev', instruction: 'hold 2500', state: 'active', adhoc: false })
    expect(d.progress.value).toBeNull()

    handlers.current!({
      type: 'step_progress', index: 0, id: 'rev_2500', pid: 'RPM', value: 2150,
      target_low: 2300, target_high: 2700, in_range: false, dwell_elapsed_s: 0, dwell_required_s: 8,
    })
    expect(d.progress.value?.value).toBe(2150)
    expect(d.progress.value?.in_range).toBe(false)

    handlers.current!({
      type: 'step_progress', index: 0, id: 'rev_2500', pid: 'RPM', value: 2500,
      target_low: 2300, target_high: 2700, in_range: true, dwell_elapsed_s: 3, dwell_required_s: 8,
    })
    expect(d.progress.value?.in_range).toBe(true)
    expect(d.progress.value?.dwell_elapsed_s).toBe(3)

    // a step boundary clears the live gauge
    handlers.current!({ type: 'step', index: 0, total: 1, id: 'rev_2500', label: 'Rev', instruction: 'hold 2500', state: 'done', adhoc: false })
    expect(d.progress.value).toBeNull()
  })

  it('enters an explicit generating phase before the report, then completes', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()
    handlers.current!({ type: 'generating' })
    expect(d.status.value).toBe('generating')

    handlers.current!({ type: 'report', overall_status: 'incomplete', summary: 'thin data', findings: [] })
    handlers.current!({ type: 'done' })
    expect(d.status.value).toBe('complete')
    expect(d.report.value?.overall_status).toBe('incomplete')
  })

  it('captures trouble codes read at session start', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()
    expect(d.codesRead.value).toBeNull()  // not yet read this run

    handlers.current!({
      type: 'codes', available: true, count: 2,
      codes: [
        { code: 'P0706', scope: 'stored', source: 'generic', description: "TR Sensor 'A' Range/Performance" },
        { code: 'P0707', scope: 'stored', source: 'generic', description: "TR Sensor 'A' Low" },
      ],
    })
    expect(d.codesRead.value).toBe(true)
    expect(d.codes.value.map((c) => c.code)).toEqual(['P0706', 'P0707'])

    // a fresh run resets the codes state
    d.start()
    await flushPromises()
    expect(d.codes.value).toEqual([])
    expect(d.codesRead.value).toBeNull()
  })

  it('marks codes unavailable when the read failed', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()
    handlers.current!({ type: 'codes', available: false, count: 0, codes: [] })
    expect(d.codesRead.value).toBe(false)
    expect(d.codes.value).toEqual([])
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
