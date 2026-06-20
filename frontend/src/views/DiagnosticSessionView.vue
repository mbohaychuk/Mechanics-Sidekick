<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useDiagnosticSession } from '@/composables/useDiagnosticSession'
import LiveFocusChart from '@/components/LiveFocusChart.vue'
import DiagnosticStep from '@/components/DiagnosticStep.vue'
import CommentaryItem from '@/components/CommentaryItem.vue'
import HealthReport from '@/components/HealthReport.vue'

const route = useRoute()
const vehicleId = Number(route.params.id)
const d = useDiagnosticSession(vehicleId)

onMounted(() => d.loadPastReports())
onUnmounted(() => d.stop())

const running = computed(() => d.status.value === 'running' || d.status.value === 'connecting')

function fmtDate(iso: string): string {
  const dt = new Date(iso)
  return Number.isNaN(dt.getTime()) ? iso : dt.toLocaleString()
}
function statusClass(s: 'good' | 'fair' | 'poor'): string {
  return { good: 'text-success', fair: 'text-warning', poor: 'text-danger' }[s]
}
const vitalNames = computed(() => Object.keys(d.latest))
const focusSeries = computed(() =>
  vitalNames.value.slice(0, 4).map((name) => ({ name, points: d.series[name] ?? [] })),
)

function fmt(name: string): string {
  const v = d.latest[name]
  if (!v || v.value === null) return '—'
  return `${v.value}${v.unit ? ' ' + v.unit : ''}`
}
function toggle() {
  if (running.value) d.stop()
  else d.start()
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-8">
    <RouterLink
      :to="{ name: 'vehicle', params: { id: vehicleId } }"
      class="mb-6 inline-flex items-center gap-1.5 font-mono text-xs text-muted/60 hover:text-muted"
    >‹ Vehicle</RouterLink>

    <header class="mb-6 flex items-center justify-between rounded-card border border-border bg-surface p-4">
      <div>
        <h1 class="font-mono text-sm font-semibold uppercase tracking-widest text-text">Diagnostic copilot</h1>
        <p class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">
          VID <span class="text-muted/70">{{ vehicleId }}</span> · {{ d.status.value }}
        </p>
      </div>
      <button
        data-test="start"
        class="rounded-md border px-4 py-2 font-mono text-xs font-semibold uppercase tracking-widest transition-all duration-150"
        :class="running ? 'border-danger/40 bg-danger/10 text-danger hover:bg-danger/20' : 'border-accent/40 bg-accent/10 text-accent hover:bg-accent/20'"
        @click="toggle"
      >{{ running ? 'Stop' : 'Start health check' }}</button>
    </header>

    <div v-if="d.status.value === 'error'" class="mb-4 rounded-md border border-danger/30 bg-danger/8 px-4 py-3">
      <p class="font-mono text-xs text-danger">{{ d.detail.value }}</p>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <!-- Left: live vitals + focus chart -->
      <section class="space-y-4">
        <ul class="overflow-hidden rounded-card border border-border bg-surface">
          <li v-for="name in vitalNames" :key="name"
              class="flex items-center justify-between border-b border-border/50 px-4 py-2 last:border-b-0">
            <span class="font-mono text-xs tracking-wider text-text/90">{{ name }}</span>
            <span class="font-mono text-sm tabular-nums" :class="fmt(name) === '—' ? 'text-muted/30' : 'text-accent'">{{ fmt(name) }}</span>
          </li>
          <li v-if="vitalNames.length === 0" class="px-4 py-6 text-center font-mono text-xs text-muted/30">
            Start the health check to stream live vitals.
          </li>
        </ul>
        <div v-if="focusSeries.length" class="overflow-hidden rounded-card border border-border bg-surface">
          <LiveFocusChart :series="focusSeries" />
        </div>
      </section>

      <!-- Right: copilot feed + report -->
      <section class="space-y-4">
        <div class="overflow-hidden rounded-card border border-border bg-surface">
          <div class="border-b border-border/50 px-4 py-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Guided steps</div>
          <DiagnosticStep
            v-for="(s, i) in d.steps.value" :key="s.id + i"
            :index="i" :label="s.label" :instruction="s.instruction" :state="s.state" :adhoc="s.adhoc"
          />
          <p v-if="d.steps.value.length === 0" class="px-4 py-6 text-center font-mono text-xs text-muted/30">No active protocol.</p>
        </div>

        <div v-if="d.anomalies.value.length" class="overflow-hidden rounded-card border border-border bg-surface">
          <div class="border-b border-border/50 px-4 py-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Live flags</div>
          <div
            v-for="(a, i) in d.anomalies.value" :key="i"
            class="flex items-start gap-3 border-b border-border/50 px-4 py-2 last:border-b-0"
          >
            <span class="font-mono text-xs font-semibold uppercase tracking-wider text-text/70">{{ a.system }}</span>
            <span
              class="text-xs"
              :class="a.severity === 'warn' ? 'text-warning' : a.severity === 'fail' ? 'text-danger' : 'text-muted'"
            >{{ a.detail }}</span>
          </div>
        </div>

        <div v-if="d.commentary.value.length" class="overflow-hidden rounded-card border border-border bg-surface">
          <div class="border-b border-border/50 px-4 py-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Live commentary</div>
          <CommentaryItem v-for="(c, i) in d.commentary.value" :key="i" :text="c.text" />
        </div>

        <HealthReport v-if="d.report.value" :report="d.report.value" />
      </section>
    </div>

    <section class="mt-8 space-y-3">
      <h2 class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Past reports</h2>
      <p v-if="d.pastError.value" class="rounded-md border border-danger/30 bg-danger/8 px-3 py-2 font-mono text-xs text-danger">
        Couldn't load past reports: {{ d.pastError.value }}
      </p>
      <ul v-if="d.pastReports.value.length" class="overflow-hidden rounded-card border border-border bg-surface">
        <li v-for="r in d.pastReports.value" :key="r.id">
          <button
            :data-test="`past-report-${r.id}`"
            class="flex w-full items-center justify-between gap-3 border-b border-border/50 px-4 py-2.5 text-left transition-colors last:border-b-0 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            @click="d.viewReport(r.id)"
          >
            <span class="min-w-0 truncate">
              <span class="font-mono text-xs text-text/90">{{ fmtDate(r.started_utc) }}</span>
              <span class="ml-2 text-xs text-muted">{{ r.summary ?? '—' }}</span>
            </span>
            <span
              v-if="r.overall_status"
              class="shrink-0 font-mono text-[0.6rem] uppercase tracking-widest"
              :class="statusClass(r.overall_status)"
            >{{ r.overall_status }}</span>
          </button>
        </li>
      </ul>
      <p v-else-if="!d.pastError.value" class="rounded-card border border-border bg-surface px-4 py-6 text-center font-mono text-xs text-muted/30">
        No past reports yet — run a health check to generate one.
      </p>
      <HealthReport v-if="d.viewedReport.value" :report="d.viewedReport.value" />
    </section>
  </main>
</template>
