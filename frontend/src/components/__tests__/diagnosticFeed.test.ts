import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import DiagnosticStep from '@/components/DiagnosticStep.vue'
import CommentaryItem from '@/components/CommentaryItem.vue'

describe('DiagnosticStep', () => {
  it('shows label, instruction, and a done marker', () => {
    const w = mount(DiagnosticStep, {
      props: { index: 0, label: 'Idle baseline', instruction: 'Let it idle', state: 'done', adhoc: false },
    })
    expect(w.text()).toContain('Idle baseline')
    expect(w.text()).toContain('Let it idle')
    expect(w.html()).toContain('✓')
  })

  it('marks the active step', () => {
    const w = mount(DiagnosticStep, {
      props: { index: 1, label: 'Rev', instruction: 'rev to 2500', state: 'active', adhoc: false },
    })
    expect(w.attributes('data-state')).toBe('active')
    expect(w.html()).toContain('2')
  })

  it('tags ad-hoc steps', () => {
    const w = mount(DiagnosticStep, {
      props: { index: 2, label: 'Hold 2000', instruction: 'hold', state: 'active', adhoc: true },
    })
    expect(w.text().toLowerCase()).toContain('added')
  })
})

describe('CommentaryItem', () => {
  it('renders the commentary text', () => {
    const w = mount(CommentaryItem, { props: { text: 'Idle looks steady.' } })
    expect(w.text()).toContain('Idle looks steady.')
  })
})
