<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import type { LiveSessionSummary } from '@/api/types'

const props = defineProps<{ vehicleId: number }>()
const emit = defineEmits<{ replay: [series: { name: string; points: [number, number][] }[]] }>()

const sessions = ref<LiveSessionSummary[]>([])
const loading = ref(false)
const active = ref<number | null>(null)

onMounted(async () => {
  loading.value = true
  sessions.value = await api.listLiveSessions(props.vehicleId)
  loading.value = false
})

async function open(id: number) {
  active.value = id
  const detail = await api.getLiveSession(id)
  const series = detail.session.pids.map((name) => ({
    name,
    points: detail.samples
      .map((s) => {
        const v = s.values[name]
        return v && typeof v.value === 'number' ? ([s.t, v.value] as [number, number]) : null
      })
      .filter((p): p is [number, number] => p !== null),
  }))
  emit('replay', series)
}

function fmtTime(utc: string): string {
  return new Date(utc).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function fmtHz(hz: number | null): string {
  return hz != null ? `${hz.toFixed(1)} Hz` : '—'
}
</script>

<template>
  <section>
    <!-- Section header -->
    <div class="mb-3 flex items-center gap-3">
      <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/40">
        Recorded sessions
      </span>
      <div class="h-px flex-1 bg-border/50" />
      <span class="font-mono text-[0.65rem] text-muted/30">
        {{ sessions.length }} session{{ sessions.length !== 1 ? 's' : '' }}
      </span>
    </div>

    <!-- Loading state -->
    <p v-if="loading" class="font-mono text-xs text-muted/30">Loading…</p>

    <!-- Empty state -->
    <p v-else-if="sessions.length === 0" class="font-mono text-xs text-muted/30">
      No recorded sessions yet.
    </p>

    <!-- Session list -->
    <ul v-else class="overflow-hidden rounded-card border border-border bg-surface">
      <li
        v-for="(s, idx) in sessions"
        :key="s.id"
        class="border-b border-border/50 last:border-b-0"
      >
        <button
          :data-session="s.id"
          class="group w-full px-4 py-2.5 text-left transition-colors duration-100 hover:bg-surface-2"
          :class="active === s.id ? 'bg-surface-2' : ''"
          @click="open(s.id)"
        >
          <div class="flex items-center gap-3">
            <!-- Index gutter -->
            <span class="w-5 shrink-0 font-mono text-[0.6rem] text-muted/25 tabular-nums">
              {{ String(idx + 1).padStart(2, '0') }}
            </span>

            <!-- Session ID -->
            <span class="w-8 shrink-0 font-mono text-xs font-semibold text-accent/80">
              #{{ s.id }}
            </span>

            <!-- Status badge -->
            <span
              class="shrink-0 rounded px-1.5 py-0.5 font-mono text-[0.6rem] uppercase tracking-widest"
              :class="{
                'bg-success/10 text-success': s.status === 'ended',
                'bg-danger/10 text-danger': s.status === 'error',
                'bg-warning/10 text-warning': s.status === 'live',
                'bg-muted/10 text-muted/50': !['ended', 'error', 'live'].includes(s.status),
              }"
            >
              {{ s.status }}
            </span>

            <!-- Timestamp -->
            <span class="flex-1 font-mono text-[0.65rem] text-muted/50 truncate">
              {{ fmtTime(s.started_utc) }}
            </span>

            <!-- Samples + Hz -->
            <span class="shrink-0 font-mono text-[0.65rem] tabular-nums text-muted/40">
              {{ s.sample_count }}&thinsp;samples
            </span>
            <span class="hidden shrink-0 font-mono text-[0.65rem] tabular-nums text-muted/30 sm:block">
              {{ fmtHz(s.achieved_hz) }}
            </span>

            <!-- Replay indicator -->
            <span
              class="shrink-0 font-mono text-[0.6rem] uppercase tracking-widest transition-colors duration-100"
              :class="active === s.id
                ? 'text-accent'
                : 'text-muted/20 group-hover:text-muted/50'"
            >
              {{ active === s.id ? '▶ replaying' : 'replay' }}
            </span>
          </div>

          <!-- PIDs row -->
          <div v-if="s.pids.length" class="mt-1 flex items-center gap-2 pl-8">
            <span
              v-for="pid in s.pids.slice(0, 6)"
              :key="pid"
              class="font-mono text-[0.6rem] text-muted/30"
            >
              {{ pid }}
            </span>
            <span v-if="s.pids.length > 6" class="font-mono text-[0.6rem] text-muted/20">
              +{{ s.pids.length - 6 }} more
            </span>
          </div>
        </button>
      </li>
    </ul>
  </section>
</template>
