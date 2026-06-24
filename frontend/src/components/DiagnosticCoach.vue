<script setup lang="ts">
import { computed } from 'vue'
import type { StepProgress } from '@/composables/useDiagnosticSession'

const props = defineProps<{
  label: string
  instruction: string
  progress: StepProgress | null
  index?: number
  total?: number
}>()

const stepCounter = computed(() =>
  props.index != null && props.total ? `Step ${props.index + 1} of ${props.total}` : '',
)

const UNIT: Record<string, string> = { RPM: 'rpm', SPEED: 'km/h', COOLANT_TEMP: '°C' }

const unit = computed(() => (props.progress ? (UNIT[props.progress.pid] ?? '') : ''))

const targetLabel = computed(() => {
  const p = props.progress
  if (!p) return ''
  const u = unit.value
  if (p.target_low != null && p.target_high != null) return `target ${p.target_low}–${p.target_high} ${u}`.trim()
  if (p.target_low != null) return `target above ${p.target_low} ${u}`.trim()
  if (p.target_high != null) return `target below ${p.target_high} ${u}`.trim()
  return ''
})

const status = computed(() => {
  const p = props.progress
  if (!p || p.value == null) return { text: 'Waiting for live data…', cls: 'text-muted' }
  if (p.in_range) return { text: 'In range — hold it steady', cls: 'text-success' }
  const u = unit.value
  if (p.target_low != null && p.value < p.target_low) {
    const goal = p.target_high != null ? `toward ${p.target_low}–${p.target_high} ${u}` : `above ${p.target_low} ${u}`
    return { text: `Bring it up ${goal}`.trim(), cls: 'text-warning' }
  }
  if (p.target_high != null && p.value > p.target_high) {
    const goal = p.target_low != null ? `toward ${p.target_low}–${p.target_high} ${u}` : `below ${p.target_high} ${u}`
    return { text: `Ease it down ${goal}`.trim(), cls: 'text-warning' }
  }
  return { text: 'Adjusting…', cls: 'text-muted' }
})

const gauge = computed(() => {
  const p = props.progress
  if (!p || (p.target_low == null && p.target_high == null)) return null
  const low = p.target_low ?? 0
  const refHigh = p.target_high ?? Math.max(low * 1.6, (p.value ?? 0) * 1.1, low + 1)
  const axisMax = Math.max(refHigh * 1.4, (p.value ?? 0) * 1.1, refHigh + 1)
  const pct = (v: number) => Math.max(0, Math.min(100, (v / axisMax) * 100))
  const bandHigh = p.target_high ?? axisMax
  return {
    bandLeft: pct(low),
    bandWidth: pct(bandHigh) - pct(low),
    valuePct: p.value == null ? null : pct(p.value),
  }
})

const dwell = computed(() => {
  const p = props.progress
  if (!p || !p.dwell_required_s) return null
  return {
    pct: Math.max(0, Math.min(100, (p.dwell_elapsed_s / p.dwell_required_s) * 100)),
    elapsed: p.dwell_elapsed_s,
    req: p.dwell_required_s,
    met: p.dwell_elapsed_s >= p.dwell_required_s,
  }
})
</script>

<template>
  <div class="rounded-card border border-accent/40 bg-surface-2 p-5 shadow-[0_0_0_1px] shadow-accent/10">
    <div class="flex items-center gap-2">
      <span class="flex h-2 w-2 rounded-full bg-accent animate-pulse" aria-hidden="true" />
      <span class="font-mono text-[0.6rem] uppercase tracking-widest text-accent">Do this now</span>
      <span v-if="stepCounter" class="font-mono text-[0.6rem] uppercase tracking-widest text-muted/40">· {{ stepCounter }}</span>
    </div>
    <p v-if="label" class="mt-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/60">{{ label }}</p>
    <p class="mt-0.5 text-base font-semibold text-text">{{ instruction }}</p>

    <template v-if="gauge">
      <!-- live gauge: target band + current-value marker -->
      <div class="mt-4 flex items-baseline justify-between font-mono text-xs">
        <span :class="status.cls">{{ status.text }}</span>
        <span class="text-text">
          {{ progress?.value ?? '–' }}<span class="text-muted/60"> {{ unit }}</span>
        </span>
      </div>
      <div class="relative mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-surface">
        <div
          class="absolute inset-y-0 rounded-full bg-success/25"
          :style="{ left: gauge.bandLeft + '%', width: gauge.bandWidth + '%' }"
        />
        <div
          v-if="gauge.valuePct !== null"
          class="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full transition-all duration-300"
          :class="progress?.in_range ? 'bg-success' : 'bg-warning'"
          :style="{ left: gauge.valuePct + '%' }"
        />
      </div>
      <p class="mt-1 text-right font-mono text-[0.6rem] text-muted/60">
        {{ targetLabel }}
      </p>

      <!-- dwell meter: how long the condition has been held -->
      <div v-if="dwell" class="mt-3">
        <div class="flex items-center justify-between font-mono text-[0.65rem] text-muted">
          <span>{{ dwell.met ? 'Held ✓' : 'Hold it…' }}</span>
          <span>{{ dwell.elapsed.toFixed(1) }} / {{ dwell.req.toFixed(1) }} s</span>
        </div>
        <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface">
          <div
            class="h-full rounded-full transition-all duration-300"
            :class="dwell.met ? 'bg-success' : 'bg-accent'"
            :style="{ width: dwell.pct + '%' }"
          />
        </div>
      </div>
    </template>

    <p v-else class="mt-3 font-mono text-xs text-muted">
      Follow the instruction — this advances automatically when detected.
    </p>
  </div>
</template>
