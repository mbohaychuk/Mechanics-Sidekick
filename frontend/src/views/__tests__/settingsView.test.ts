import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    getConfig: vi.fn().mockResolvedValue({
      openai_key_present: true, obd_mcp_enabled: false, obd_port: 'socket://localhost:35000',
      web_search_enabled: true, web_search_key_present: false,
      chat_model: 'gpt-4.1-mini', embed_model: 'text-embedding-3-small',
    }),
    getScannerStatus: vi.fn().mockResolvedValue({ available: false, scanner_reachable: false, detail: 'OBD tool server not running.' }),
  },
}))

import SettingsView from '@/views/SettingsView.vue'

beforeEach(() => setActivePinia(createPinia()))

describe('SettingsView', () => {
  it('renders config status without leaking secrets', async () => {
    const wrapper = mount(SettingsView)
    await flushPromises()
    expect(wrapper.text()).toContain('gpt-4.1-mini')
    expect(wrapper.text()).toContain('socket://localhost:35000')
    expect(wrapper.text().toLowerCase()).toContain('openai')
  })
})
