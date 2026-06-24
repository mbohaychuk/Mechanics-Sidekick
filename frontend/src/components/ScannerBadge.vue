<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useScannerStore } from '@/stores/scanner'

const scanner = useScannerStore()
// Poll so the badge flips between connected / not-connected live when a scanner is plugged in or
// pulled — no page reload needed.
onMounted(() => scanner.startPolling())
onUnmounted(() => scanner.stopPolling())

const tone = computed(() => {
  const s = scanner.status
  if (s?.scanner_reachable) return 'bg-success'
  if (s?.available) return 'bg-warning'
  return 'bg-danger'
})
const label = computed(() => scanner.status?.detail ?? 'Scanner not connected.')
</script>

<template>
  <div
    class="flex items-center gap-2 rounded-full border border-border bg-surface-2 px-2 py-1.5 sm:px-3"
    role="status"
    :aria-label="label"
  >
    <!-- Pulsing status dot -->
    <span class="relative flex h-2 w-2 shrink-0">
      <span
        class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
        :class="tone"
      />
      <span
        class="relative inline-flex h-2 w-2 rounded-full"
        :class="tone"
      />
    </span>
    <!-- Status label — hidden on narrow screens (dot conveys status; aria-label covers SR) -->
    <span class="hidden whitespace-nowrap font-mono text-xs tracking-wide text-muted sm:inline">{{ label }}</span>
  </div>
</template>
