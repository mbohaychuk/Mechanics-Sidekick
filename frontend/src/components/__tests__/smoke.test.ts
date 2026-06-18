import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import VehiclesView from '@/views/VehiclesView.vue'

describe('scaffold', () => {
  it('renders the app heading', () => {
    const wrapper = mount(VehiclesView)
    expect(wrapper.text()).toContain('Mechanic Sidekick')
  })
})
