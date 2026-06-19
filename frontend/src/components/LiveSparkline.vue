<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import '@/echarts'
import type { ECOption } from '@/echarts'

const props = defineProps<{ points: [number, number][] }>()

const option = computed<ECOption>(() => ({
  animation: false,
  grid: { top: 2, bottom: 2, left: 2, right: 2 },
  xAxis: { type: 'value', show: false },
  yAxis: { type: 'value', show: false, scale: true },
  series: [{ type: 'line', data: props.points, showSymbol: false, lineStyle: { width: 1.5 } }],
}))
</script>

<template>
  <VChart :option="option" :init-options="{ renderer: 'svg' }" autoresize class="h-8 w-28" />
</template>
