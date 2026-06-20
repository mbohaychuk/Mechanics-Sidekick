<script setup lang="ts">
import { computed } from 'vue'
import type { DiagnosticReport } from '@/api/types'

const props = defineProps<{ report: DiagnosticReport }>()

const overallClass = computed(() => ({
  good: 'border-success/40 bg-success/10 text-success',
  fair: 'border-warning/40 bg-warning/10 text-warning',
  poor: 'border-danger/40 bg-danger/10 text-danger',
}[props.report.overall_status]))

function sources(evidence: Record<string, unknown>): { filename?: string; page?: number }[] {
  const s = evidence?.sources
  return Array.isArray(s) ? (s as { filename?: string; page?: number }[]) : []
}
</script>

<template>
  <section class="rounded-card border border-border bg-surface p-4">
    <div class="mb-3 flex items-center gap-3">
      <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Health report</span>
      <div class="h-px flex-1 bg-border/50" />
      <span
        class="rounded-md border px-2.5 py-1 font-mono text-[0.65rem] font-semibold uppercase tracking-widest"
        :class="overallClass"
      >{{ report.overall_status }}</span>
    </div>

    <p class="mb-4 text-sm leading-relaxed text-text/90">{{ report.summary }}</p>

    <ul class="space-y-2">
      <li
        v-for="f in report.findings"
        :key="f.system"
        :data-system="f.system"
        :data-severity="f.severity"
        class="rounded-md border border-border/60 bg-surface-2 px-3 py-2.5"
      >
        <div class="flex items-center gap-2">
          <span
            class="h-2 w-2 shrink-0 rounded-full"
            :class="{ 'bg-success': f.severity === 'good', 'bg-warning': f.severity === 'warn', 'bg-danger': f.severity === 'fail' }"
          />
          <span class="font-mono text-xs font-semibold uppercase tracking-wider text-text">{{ f.system }}</span>
          <span class="font-mono text-[0.6rem] uppercase tracking-widest text-muted/50">{{ f.severity }}</span>
        </div>
        <p class="mt-1.5 text-xs text-text/80">{{ f.observation }}</p>
        <p v-if="f.interpretation" class="mt-1 text-xs text-muted">{{ f.interpretation }}</p>
        <p v-if="f.recommendation" class="mt-1 text-xs text-accent/90">→ {{ f.recommendation }}</p>
        <ul v-if="sources(f.evidence).length" class="mt-1.5 text-[0.65rem] text-muted/60">
          <li v-for="(s, i) in sources(f.evidence)" :key="i" class="font-mono">
            › {{ s.filename }}<template v-if="s.page"> · p.{{ s.page }}</template>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>
