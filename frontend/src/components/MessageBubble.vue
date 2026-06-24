<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/markdown'

const props = defineProps<{ role: string; content: string; sources?: Array<Record<string, unknown>> | null; error?: string }>()

// Only the assistant's text is markdown (the model writes **bold**, lists, `code`, etc.); user text
// is shown verbatim so their literal characters are never reinterpreted as formatting.
const renderedContent = computed(() => renderMarkdown(props.content))
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
      <!-- Rendered markdown once tokens arrive; a blinking cursor while the turn is still empty (streaming) -->
      <!-- eslint-disable-next-line vue/no-v-html -- input is markdown-it output with html:false (see markdown.ts) -->
      <div v-if="content" class="md-body" v-html="renderedContent" />
      <span v-else-if="!error" class="inline-block w-[2px] h-[1em] bg-accent/70 align-text-bottom animate-[cursor-blink_0.9s_step-end_infinite]" aria-hidden="true" />

      <!-- Handled error, kept visually distinct from the answer text -->
      <div v-if="error" class="mt-2 flex items-start gap-2 rounded-md border border-danger/30 bg-danger/8 px-3 py-2">
        <span class="font-mono text-[0.7rem] text-danger">{{ error }}</span>
      </div>

      <!-- Sources -->
      <ul v-if="sources?.length" class="mt-3 border-t border-border/60 pt-2.5 text-xs text-muted">
        <li
          v-for="(s, i) in sources"
          :key="i"
          class="flex items-center gap-1.5 font-mono leading-5"
        >
          <span class="text-accent/50 select-none">›</span>
          <template v-if="s.kind === 'diagnostic'">
            <span>Health check</span>
            <span class="text-muted/40">·</span>
            <span class="text-muted/70">{{ s.date }}</span>
            <span class="text-muted/40">·</span>
            <span class="uppercase text-muted/70">{{ s.overall_status }}</span>
          </template>
          <template v-else-if="s.kind === 'recall'">
            <span>Recall {{ s.campaign }}</span>
            <template v-if="s.component">
              <span class="text-muted/40">·</span>
              <span class="text-muted/70">{{ s.component }}</span>
            </template>
          </template>
          <template v-else>
            <span>{{ (s.filename as string) ?? (s.url as string) }}</span>
            <template v-if="s.page">
              <span class="text-muted/40">·</span>
              <span class="text-muted/70">p.{{ s.page }}</span>
            </template>
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

/* Markdown rendering for assistant messages (v-html content needs :deep to pierce scoping). */
.md-body :deep(p) { margin: 0; }
.md-body :deep(p + p) { margin-top: 0.6rem; }
.md-body :deep(strong) { font-weight: 600; color: var(--color-text); }
.md-body :deep(em) { font-style: italic; }
.md-body :deep(a) { color: var(--color-accent); text-decoration: underline; text-underline-offset: 2px; }
.md-body :deep(ul),
.md-body :deep(ol) { margin: 0.4rem 0; padding-left: 1.25rem; }
.md-body :deep(ul) { list-style: disc; }
.md-body :deep(ol) { list-style: decimal; }
.md-body :deep(li) { margin: 0.15rem 0; }
.md-body :deep(li::marker) { color: var(--color-accent); }
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) { font-weight: 600; margin: 0.6rem 0 0.3rem; line-height: 1.3; }
.md-body :deep(h1) { font-size: 1.05rem; }
.md-body :deep(h2) { font-size: 1rem; }
.md-body :deep(h3) { font-size: 0.95rem; }
.md-body :deep(code) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.85em;
  background: color-mix(in oklab, var(--color-accent) 12%, transparent);
  border-radius: 4px;
  padding: 0.05rem 0.3rem;
}
.md-body :deep(pre) {
  margin: 0.5rem 0;
  padding: 0.6rem 0.75rem;
  background: color-mix(in oklab, var(--color-text) 6%, transparent);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  overflow-x: auto;
}
.md-body :deep(pre code) { background: none; padding: 0; font-size: 0.82em; }
.md-body :deep(blockquote) {
  margin: 0.5rem 0;
  padding-left: 0.75rem;
  border-left: 2px solid var(--color-border);
  color: var(--color-muted);
}
.md-body :deep(table) { border-collapse: collapse; margin: 0.5rem 0; font-size: 0.9em; }
.md-body :deep(th),
.md-body :deep(td) { border: 1px solid var(--color-border); padding: 0.25rem 0.5rem; text-align: left; }
.md-body :deep(hr) { border: none; border-top: 1px solid var(--color-border); margin: 0.6rem 0; }
</style>
