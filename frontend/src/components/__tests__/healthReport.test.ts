import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import HealthReport from '@/components/HealthReport.vue'
import type { DiagnosticReport } from '@/api/types'

const report: DiagnosticReport = {
  overall_status: 'fair',
  summary: 'One lean bank, otherwise healthy.',
  findings: [
    { system: 'fuel', severity: 'warn', observation: 'LTFT +14% at 2500 rpm',
      interpretation: 'Running lean under load.', recommendation: 'Check for a vacuum leak.',
      evidence: { sources: [{ filename: 'service.pdf', page: 142 }] } },
    { system: 'cooling', severity: 'good', observation: 'Coolant held at 88C',
      interpretation: '', recommendation: '', evidence: {} },
  ],
}

describe('HealthReport', () => {
  it('renders overall status, summary, findings, and citations', () => {
    const w = mount(HealthReport, { props: { report } })
    expect(w.text().toLowerCase()).toContain('fair')
    expect(w.text()).toContain('One lean bank')
    expect(w.text()).toContain('fuel')
    expect(w.text()).toContain('Check for a vacuum leak.')
    expect(w.text()).toContain('service.pdf')
    expect(w.text()).toContain('142')
  })

  it('applies severity styling per finding', () => {
    const w = mount(HealthReport, { props: { report } })
    const fuel = w.find('[data-system="fuel"]')
    expect(fuel.attributes('data-severity')).toBe('warn')
    const cooling = w.find('[data-system="cooling"]')
    expect(cooling.attributes('data-severity')).toBe('good')
  })
})
