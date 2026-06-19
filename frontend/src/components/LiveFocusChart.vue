<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import '@/echarts'
import type { ECOption } from '@/echarts'

const props = defineProps<{ series: { name: string; points: [number, number][] }[] }>()

const option = computed<ECOption>(() => ({
  grid: { left: 48, right: 16, top: 24, bottom: 48 },
  tooltip: { trigger: 'axis' },
  legend: { top: 0, textStyle: { color: '#8b97a6' } },
  xAxis: { type: 'value', name: 't (ms)', axisLabel: { color: '#8b97a6' } },
  yAxis: { type: 'value', scale: true, axisLabel: { color: '#8b97a6' } },
  dataZoom: [{ type: 'inside' }],
  series: props.series.map((s) => ({
    type: 'line',
    name: s.name,
    data: s.points,
    showSymbol: false,
    lineStyle: { width: 2 },
  })),
}))
</script>

<template>
  <VChart :option="option" :init-options="{ renderer: 'svg' }" autoresize class="h-72 w-full" />
</template>
