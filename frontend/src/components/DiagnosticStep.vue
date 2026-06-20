<script setup lang="ts">
defineProps<{
  index: number
  label: string
  instruction: string
  state: 'pending' | 'active' | 'done' | 'skipped'
  adhoc: boolean
}>()
</script>

<template>
  <div
    :data-state="state"
    class="flex items-start gap-3 border-b border-border/50 px-4 py-3 last:border-b-0"
    :class="state === 'active' ? 'bg-surface-2' : ''"
  >
    <span
      class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[0.65rem]"
      :class="{
        'bg-success/15 text-success': state === 'done',
        'bg-accent/15 text-accent animate-pulse': state === 'active',
        'bg-muted/15 text-muted/50': state === 'pending',
        'bg-warning/15 text-warning': state === 'skipped',
      }"
    >
      <template v-if="state === 'done'">✓</template>
      <template v-else-if="state === 'skipped'">–</template>
      <template v-else>{{ index + 1 }}</template>
    </span>
    <div class="min-w-0">
      <p class="font-mono text-xs font-semibold tracking-wider text-text">
        {{ label }}
        <span v-if="adhoc" class="ml-1.5 rounded bg-accent/15 px-1 py-0.5 text-[0.55rem] uppercase tracking-widest text-accent">added</span>
      </p>
      <p class="mt-0.5 text-xs text-muted">{{ instruction }}</p>
    </div>
  </div>
</template>
