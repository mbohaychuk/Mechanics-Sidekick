<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import { useLiveSession } from '@/composables/useLiveSession'
import type { SupportedPid } from '@/api/types'
import LiveSparkline from '@/components/LiveSparkline.vue'
import LiveFocusChart from '@/components/LiveFocusChart.vue'

const route = useRoute()
const vehicleId = Number(route.params.id)
const live = useLiveSession(vehicleId)

const supported = ref<SupportedPid[]>([])
const available = ref(false)
const selected = ref<string[]>([])
const pinned = ref<string[]>([])

onMounted(async () => {
  const res = await api.getSupportedPids(vehicleId)
  available.value = res.available
  supported.value = res.supported
  const supportedNames = new Set(res.supported.map((p) => p.name))
  const defaults = res.curated.filter((p) => supportedNames.has(p))
  selected.value = defaults.length ? defaults : res.curated
  pinned.value = selected.value.slice(0, 1)
})

onUnmounted(() => live.stop())

const addable = computed(() =>
  supported.value.filter((p) => !selected.value.includes(p.name)),
)
const focusSeries = computed(() =>
  pinned.value.map((name) => ({ name, points: live.series[name] ?? [] })),
)

function toggleStart() {
  if (live.status.value === 'streaming' || live.status.value === 'connecting') live.stop()
  else live.start(selected.value)
}
function addPid(name: string) {
  if (!selected.value.includes(name)) selected.value.push(name)
}
function removePid(name: string) {
  selected.value = selected.value.filter((p) => p !== name)
  pinned.value = pinned.value.filter((p) => p !== name)
}
function togglePin(name: string) {
  pinned.value = pinned.value.includes(name)
    ? pinned.value.filter((p) => p !== name)
    : [...pinned.value, name]
}
function fmt(name: string): string {
  const v = live.latest[name]
  if (!v || v.value === null) return '—'
  return `${v.value}${v.unit ? ' ' + v.unit : ''}`
}

const isStreaming = computed(
  () => live.status.value === 'streaming' || live.status.value === 'connecting',
)
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-8">

    <!-- Back nav -->
    <RouterLink
      :to="{ name: 'vehicle', params: { id: vehicleId } }"
      class="group mb-6 inline-flex items-center gap-1.5 font-mono text-xs text-muted/60 transition-colors duration-150 hover:text-muted"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        class="h-3.5 w-3.5 transition-transform duration-150 group-hover:-translate-x-0.5"
        aria-hidden="true">
        <path d="m15 18-6-6 6-6"/>
      </svg>
      Vehicle
    </RouterLink>

    <!-- Instrument header bar -->
    <header class="mb-6 rounded-card border border-border bg-surface p-4">
      <div class="flex flex-wrap items-center justify-between gap-4">

        <!-- Left: title + VIN -->
        <div class="flex items-center gap-3">
          <!-- Status lamp -->
          <span
            class="relative flex h-2.5 w-2.5 shrink-0"
            :title="live.status.value"
          >
            <span
              v-if="live.status.value === 'streaming'"
              class="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75"
            />
            <span
              class="relative inline-flex h-2.5 w-2.5 rounded-full"
              :class="{
                'bg-success': live.status.value === 'streaming',
                'bg-warning animate-pulse': live.status.value === 'connecting',
                'bg-danger': live.status.value === 'error',
                'bg-muted/30': live.status.value === 'idle',
              }"
            />
          </span>
          <div>
            <h1 class="font-mono text-sm font-semibold uppercase tracking-widest text-text">
              Live telemetry
            </h1>
            <p class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">
              VID&nbsp;<span class="text-muted/70">{{ vehicleId }}</span>
            </p>
          </div>
        </div>

        <!-- Right: Hz readout + Start/Stop -->
        <div class="flex items-center gap-4">
          <!-- Hz counter -->
          <div class="text-right">
            <div class="font-mono text-base font-semibold leading-none tabular-nums"
              :class="isStreaming ? 'text-accent' : 'text-muted/30'">
              {{ isStreaming && live.achievedHz.value ? live.achievedHz.value : '—' }}
            </div>
            <div class="mt-0.5 font-mono text-[0.6rem] uppercase tracking-widest text-muted/40">Hz</div>
          </div>

          <!-- Status text -->
          <div class="hidden text-right sm:block">
            <div class="font-mono text-[0.65rem] uppercase tracking-widest"
              :class="{
                'text-success': live.status.value === 'streaming',
                'text-warning': live.status.value === 'connecting',
                'text-danger': live.status.value === 'error',
                'text-muted/40': live.status.value === 'idle',
              }">
              {{ live.status.value }}
            </div>
          </div>

          <!-- Start / Stop button -->
          <button
            class="rounded-md border px-4 py-2 font-mono text-xs font-semibold uppercase tracking-widest transition-all duration-150"
            :class="isStreaming
              ? 'border-danger/40 bg-danger/10 text-danger hover:bg-danger/20'
              : 'border-accent/40 bg-accent/10 text-accent hover:bg-accent/20'"
            @click="toggleStart"
          >
            {{ isStreaming ? 'Stop' : 'Start' }}
          </button>
        </div>
      </div>
    </header>

    <!-- VIN mismatch banner -->
    <div
      v-if="live.vinMismatch.value"
      class="mb-4 flex items-start gap-2.5 rounded-md border border-warning/30 bg-warning/8 px-4 py-3"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
        class="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <p class="font-mono text-xs text-warning">{{ live.vinMismatch.value }}</p>
    </div>

    <!-- Error banner -->
    <div
      v-if="live.status.value === 'error'"
      class="mb-4 flex items-start gap-2.5 rounded-md border border-danger/30 bg-danger/8 px-4 py-3"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
        class="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <p class="font-mono text-xs text-danger">{{ live.detail.value }}</p>
    </div>

    <!-- PIDs feed -->
    <section class="mb-6">
      <!-- Section header -->
      <div class="mb-2 flex items-center gap-3">
        <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/40">Channels</span>
        <div class="h-px flex-1 bg-border/50" />
        <span class="font-mono text-[0.65rem] text-muted/30">{{ selected.length }} active</span>
      </div>

      <!-- Vitals list — instrument-panel rows -->
      <ul class="overflow-hidden rounded-card border border-border bg-surface">
        <li
          v-for="(name, idx) in selected"
          :key="name"
          class="group flex items-center gap-3 border-b border-border/50 px-4 py-2.5 last:border-b-0 transition-colors duration-100 hover:bg-surface-2"
          :style="{ animationDelay: `${idx * 40}ms` }"
        >
          <!-- PID index gutter -->
          <span class="w-5 shrink-0 font-mono text-[0.6rem] text-muted/25 tabular-nums">
            {{ String(idx + 1).padStart(2, '0') }}
          </span>

          <!-- PID name -->
          <span class="w-36 shrink-0 font-mono text-xs font-medium tracking-wider text-text/90">
            {{ name }}
          </span>

          <!-- Live value -->
          <span
            class="w-24 shrink-0 text-right font-mono text-sm tabular-nums transition-colors duration-200"
            :class="fmt(name) === '—' ? 'text-muted/30' : 'text-accent'"
          >
            {{ fmt(name) }}
          </span>

          <!-- Sparkline -->
          <div class="flex-1">
            <LiveSparkline :points="live.series[name] ?? []" />
          </div>

          <!-- Pin toggle -->
          <button
            class="shrink-0 rounded px-1.5 py-0.5 font-mono text-[0.6rem] uppercase tracking-widest transition-colors duration-100"
            :class="pinned.includes(name)
              ? 'bg-accent/15 text-accent'
              : 'text-muted/30 hover:text-muted/60'"
            :title="pinned.includes(name) ? 'Unpin from focus chart' : 'Pin to focus chart'"
            @click="togglePin(name)"
          >
            pin
          </button>

          <!-- Remove -->
          <button
            class="shrink-0 rounded px-1.5 py-0.5 font-mono text-[0.6rem] text-muted/20 opacity-0 transition-opacity duration-100 group-hover:opacity-100 hover:text-danger"
            title="Remove channel"
            @click="removePid(name)"
          >
            ✕
          </button>
        </li>

        <!-- Empty state -->
        <li v-if="selected.length === 0" class="px-4 py-6 text-center font-mono text-xs text-muted/30">
          No channels selected — add one below
        </li>
      </ul>
    </section>

    <!-- PID picker -->
    <section class="mb-8">
      <div class="flex items-center gap-3">
        <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/40">Add channel</span>
        <div class="h-px flex-1 bg-border/50" />
      </div>
      <div class="mt-2 flex items-center gap-3">
        <select
          class="flex-1 rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-xs text-text outline-none transition-colors duration-150 focus:border-accent/50 focus:ring-1 focus:ring-accent/20 disabled:opacity-40"
          :disabled="addable.length === 0"
          @change="addPid(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''"
        >
          <option value="">{{ addable.length ? '+ Select PID…' : 'All supported PIDs active' }}</option>
          <option v-for="p in addable" :key="p.name" :value="p.name">
            {{ p.name }} — {{ p.description }}
          </option>
        </select>
      </div>
    </section>

    <!-- Focus chart -->
    <section v-if="pinned.length">
      <div class="mb-2 flex items-center gap-3">
        <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/40">Focus</span>
        <div class="h-px flex-1 bg-border/50" />
        <span class="font-mono text-[0.65rem] text-muted/30">{{ pinned.join(' · ') }}</span>
      </div>
      <div class="overflow-hidden rounded-card border border-border bg-surface">
        <LiveFocusChart :series="focusSeries" />
      </div>
    </section>

    <!-- No scanner available notice -->
    <p v-if="!available && supported.length === 0" class="mt-6 text-center font-mono text-xs text-muted/30">
      No OBD scanner detected. Connect a scanner and reload.
    </p>

  </main>
</template>
