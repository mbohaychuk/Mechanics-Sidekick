<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useScannerStore } from '@/stores/scanner'

const scanner = useScannerStore()
onMounted(() => scanner.refresh())

const tone = computed(() => {
  const s = scanner.status
  if (s?.scanner_reachable) return 'bg-success'
  if (s?.available) return 'bg-warning'
  return 'bg-danger'
})
const label = computed(() => scanner.status?.detail ?? 'Scanner not connected.')
</script>

<template>
  <div class="flex items-center gap-2 rounded-full border border-border bg-surface-2 px-3 py-1.5">
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
    <!-- Status label -->
    <span class="font-mono text-xs tracking-wide text-muted">{{ label }}</span>
  </div>
</template>
