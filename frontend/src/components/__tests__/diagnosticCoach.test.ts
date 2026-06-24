import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import DiagnosticCoach from '@/components/DiagnosticCoach.vue'

const base = { label: 'Rev to 2500', instruction: 'Hold the engine at about 2500 rpm.' }

function progress(over: Record<string, unknown> = {}) {
  return {
    index: 2, id: 'rev_2500', pid: 'RPM', value: 2500, target_low: 2300, target_high: 2700,
    in_range: true, dwell_elapsed_s: 4, dwell_required_s: 8, ...over,
  }
}

describe('DiagnosticCoach', () => {
  it('always shows the active instruction', () => {
    const w = mount(DiagnosticCoach, { props: { ...base, progress: null } })
    expect(w.text()).toContain('2500 rpm')
    expect(w.text().toLowerCase()).toContain('do this now')
  })

  it('coaches the operator UP toward the band when below target', () => {
    const w = mount(DiagnosticCoach, {
      props: { ...base, progress: progress({ value: 1800, in_range: false, dwell_elapsed_s: 0 }) },
    })
    expect(w.text().toLowerCase()).toContain('bring it up')
    expect(w.text()).toContain('1800')
  })

  it('confirms when in range and shows held dwell progress', () => {
    const w = mount(DiagnosticCoach, { props: { ...base, progress: progress() } })
    expect(w.text().toLowerCase()).toContain('hold it steady')
    expect(w.text()).toMatch(/4\.0\s*\/\s*8\.0\s*s/)
  })

  it('marks the dwell as held once the requirement is met', () => {
    const w = mount(DiagnosticCoach, {
      props: { ...base, progress: progress({ dwell_elapsed_s: 8 }) },
    })
    expect(w.text()).toContain('Held ✓')
  })
})
