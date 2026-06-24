import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import type { ChatStreamEvent } from '@/api/chatStream'

vi.mock('@/api/client', () => ({
  api: { listMessages: vi.fn().mockResolvedValue([]) },
}))
vi.mock('@/api/chatStream', () => ({
  streamChatMessage: vi.fn(async (_jobId: number, _content: string, onEvent: (e: ChatStreamEvent) => void) => {
    onEvent({ type: 'tool_call', name: 'search_manuals', arguments: { query: 'oil' } })
    onEvent({ type: 'tool_result', name: 'search_manuals' })
    onEvent({ type: 'token', text: 'Use ' })
    onEvent({ type: 'token', text: '5W-30.' })
    onEvent({ type: 'sources', sources: [{ filename: 'm.pdf', page: 3 }] })
    onEvent({ type: 'done' })
  }),
}))

import ChatView from '@/views/ChatView.vue'

function mountChat() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/jobs/:id/chat', name: 'chat', component: ChatView },
  ] })
  router.push('/jobs/1/chat')
  return router.isReady().then(() => mount(ChatView, { global: { plugins: [router] } }))
}

beforeEach(() => setActivePinia(createPinia()))

describe('ChatView', () => {
  it('streams an assistant answer with tool activity and sources', async () => {
    const wrapper = await mountChat()
    await flushPromises()

    await wrapper.find('textarea').setValue('what oil?')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Use 5W-30.')          // streamed tokens assembled
    expect(wrapper.text()).toContain('Searching manuals')    // tool chip (human-readable label)
    expect(wrapper.text()).toContain('m.pdf')                // source citation
  })
})
