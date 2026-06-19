<script setup lang="ts">
defineProps<{ role: string; content: string; sources?: Array<Record<string, unknown>> | null }>()
</script>

<template>
  <div class="bubble-row mb-4" :class="role === 'user' ? 'flex justify-end' : 'flex justify-start'">
    <!-- User bubble -->
    <div
      v-if="role === 'user'"
      class="max-w-[72%] rounded-2xl rounded-br-sm bg-accent px-4 py-2.5 text-sm font-medium text-bg shadow-sm"
    >
      {{ content }}
    </div>

    <!-- Assistant bubble -->
    <div
      v-else
      class="max-w-[82%] rounded-2xl rounded-bl-sm border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-text shadow-sm"
    >
      <!-- Content with cursor blink if empty (streaming) -->
      <span class="whitespace-pre-wrap">{{ content }}</span><span v-if="!content" class="inline-block w-[2px] h-[1em] bg-accent/70 align-text-bottom animate-[cursor-blink_0.9s_step-end_infinite]" aria-hidden="true" />

      <!-- Sources -->
      <ul v-if="sources?.length" class="mt-3 border-t border-border/60 pt-2.5 text-xs text-muted">
        <li
          v-for="(s, i) in sources"
          :key="i"
          class="flex items-center gap-1.5 font-mono leading-5"
        >
          <span class="text-accent/50 select-none">›</span>
          <span>{{ (s.filename as string) ?? (s.url as string) }}</span>
          <template v-if="s.page">
            <span class="text-muted/40">·</span>
            <span class="text-muted/70">p.{{ s.page }}</span>
          </template>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.bubble-row {
  animation: bubble-in 0.2s ease both;
}
@keyframes bubble-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
</style>
