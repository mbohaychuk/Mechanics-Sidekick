import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import MessageBubble from '@/components/MessageBubble.vue'

describe('MessageBubble sources', () => {
  it('renders a manual source (filename + page)', () => {
    const w = mount(MessageBubble, {
      props: { role: 'assistant', content: 'Use 5W-30.', sources: [{ filename: 'm.pdf', page: 3 }] },
    })
    expect(w.text()).toContain('m.pdf')
    expect(w.text()).toContain('p.3')
  })

  it('renders a diagnostic source (date + status)', () => {
    const w = mount(MessageBubble, {
      props: {
        role: 'assistant', content: 'Last check was fair.',
        sources: [{ kind: 'diagnostic', session_id: 7, date: '2026-06-15', overall_status: 'fair' }],
      },
    })
    expect(w.text().toLowerCase()).toContain('health check')
    expect(w.text()).toContain('2026-06-15')
    expect(w.text().toLowerCase()).toContain('fair')
  })
})
