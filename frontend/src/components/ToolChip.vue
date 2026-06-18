<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ name: string; active?: boolean }>()
const icon = computed(() => {
  if (props.name === 'search_manuals') return '📖'
  if (props.name === 'web_search') return '🔎'
  return '🔧'
})
</script>

<template>
  <span
    class="tool-chip inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-0.5 font-mono text-xs text-muted transition-colors duration-300"
    :class="active ? 'border-accent/40 text-accent/80' : ''"
  >
    <span class="text-[0.7rem] leading-none">{{ icon }}</span>
    <span class="tracking-tight">{{ name }}</span>
  </span>
</template>

<style scoped>
.tool-chip {
  animation: chip-fade-in 0.25s ease both;
}
@keyframes chip-fade-in {
  from { opacity: 0; transform: translateY(4px) scale(0.95); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
