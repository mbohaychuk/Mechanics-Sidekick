import { mount } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/client', () => ({ api: { getScannerStatus: vi.fn().mockResolvedValue({ available: true, scanner_reachable: true, detail: 'Scanner connected.' }) } }))

import ScannerBadge from '@/components/ScannerBadge.vue'
import { useScannerStore } from '@/stores/scanner'

beforeEach(() => setActivePinia(createPinia()))

describe('ScannerBadge', () => {
  it('shows the scanner detail once refreshed', async () => {
    const store = useScannerStore()
    await store.refresh()
    const wrapper = mount(ScannerBadge)
    expect(wrapper.text()).toContain('Scanner connected.')
  })

  it('shows a disconnected state when unavailable', () => {
    const wrapper = mount(ScannerBadge)
    expect(wrapper.text().toLowerCase()).toContain('not')
  })
})
