import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'initOptions', 'autoresize', 'manualUpdate'], template: '<div class="v-chart-stub" />' },
}))

import LiveSparkline from '@/components/LiveSparkline.vue'
import LiveFocusChart from '@/components/LiveFocusChart.vue'

function chartOption(wrapper: ReturnType<typeof mount>) {
  return wrapper.findComponent({ name: 'VChart' }).props('option') as {
    series: { data: [number, number][]; name?: string }[]
  }
}

describe('LiveSparkline', () => {
  it('puts the points into a single line series', () => {
    const wrapper = mount(LiveSparkline, { props: { points: [[0, 800], [1000, 820]] } })
    expect(wrapper.find('.v-chart-stub').exists()).toBe(true)
    expect(chartOption(wrapper).series[0].data).toEqual([[0, 800], [1000, 820]])
  })
})

describe('LiveFocusChart', () => {
  it('renders one series per input series with names', () => {
    const wrapper = mount(LiveFocusChart, {
      props: { series: [{ name: 'RPM', points: [[0, 800]] }, { name: 'SPEED', points: [[0, 0]] }] },
    })
    const opt = chartOption(wrapper)
    expect(opt.series.map((s) => s.name)).toEqual(['RPM', 'SPEED'])
    expect(opt.series[0].data).toEqual([[0, 800]])
  })
})
