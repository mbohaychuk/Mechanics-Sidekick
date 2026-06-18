<script setup lang="ts">
import { onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useScannerStore } from '@/stores/scanner'

const config = useConfigStore()
const scanner = useScannerStore()

onMounted(() => {
  config.load()
  scanner.refresh()
})

function yn(v: boolean | undefined) {
  return v ? 'yes' : 'no'
}
</script>

<template>
  <main class="mx-auto max-w-2xl px-6 py-8">

    <!-- Page header -->
    <div class="mb-8">
      <h1 class="font-mono text-2xl font-semibold tracking-tight text-text">
        System Config
      </h1>
      <p class="mt-1 font-mono text-xs uppercase tracking-widest text-muted/50">
        Read-only · runtime values
      </p>
    </div>

    <!-- Loading skeleton -->
    <div v-if="!config.config" class="space-y-3">
      <div v-for="i in 5" :key="i" class="h-10 animate-pulse rounded-md bg-surface-2" />
    </div>

    <template v-else>

      <!-- AI Section -->
      <section class="mb-6">
        <div class="mb-3 flex items-center gap-3">
          <span class="font-mono text-xs font-semibold uppercase tracking-widest text-accent">
            AI / Models
          </span>
          <div class="h-px flex-1 bg-border" />
        </div>
        <div class="space-y-px overflow-hidden rounded-card border border-border">

          <!-- OpenAI key -->
          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">OpenAI key present</span>
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium"
              :class="config.config.openai_key_present
                ? 'bg-success/10 text-success'
                : 'bg-danger/10 text-danger'"
            >
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="config.config.openai_key_present ? 'bg-success' : 'bg-danger'"
              />
              {{ yn(config.config.openai_key_present) }}
            </span>
          </div>

          <!-- Chat model -->
          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">Chat model</span>
            <code class="rounded bg-surface-2 px-2 py-0.5 font-mono text-xs text-accent">
              {{ config.config.chat_model }}
            </code>
          </div>

          <!-- Embedding model -->
          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">Embedding model</span>
            <code class="rounded bg-surface-2 px-2 py-0.5 font-mono text-xs text-accent">
              {{ config.config.embed_model }}
            </code>
          </div>

        </div>
      </section>

      <!-- Web search section -->
      <section class="mb-6">
        <div class="mb-3 flex items-center gap-3">
          <span class="font-mono text-xs font-semibold uppercase tracking-widest text-accent">
            Web Search
          </span>
          <div class="h-px flex-1 bg-border" />
        </div>
        <div class="space-y-px overflow-hidden rounded-card border border-border">

          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">Web search enabled</span>
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium"
              :class="config.config.web_search_enabled
                ? 'bg-success/10 text-success'
                : 'bg-surface-2 text-muted'"
            >
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="config.config.web_search_enabled ? 'bg-success' : 'bg-muted'"
              />
              {{ yn(config.config.web_search_enabled) }}
            </span>
          </div>

          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">Search key present</span>
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium"
              :class="config.config.web_search_key_present
                ? 'bg-success/10 text-success'
                : 'bg-danger/10 text-danger'"
            >
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="config.config.web_search_key_present ? 'bg-success' : 'bg-danger'"
              />
              {{ yn(config.config.web_search_key_present) }}
            </span>
          </div>

        </div>
      </section>

      <!-- OBD / Scanner section -->
      <section class="mb-6">
        <div class="mb-3 flex items-center gap-3">
          <span class="font-mono text-xs font-semibold uppercase tracking-widest text-accent">
            OBD / Scanner
          </span>
          <div class="h-px flex-1 bg-border" />
        </div>
        <div class="space-y-px overflow-hidden rounded-card border border-border">

          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">OBD tools enabled</span>
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium"
              :class="config.config.obd_mcp_enabled
                ? 'bg-success/10 text-success'
                : 'bg-surface-2 text-muted'"
            >
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="config.config.obd_mcp_enabled ? 'bg-success' : 'bg-muted'"
              />
              {{ yn(config.config.obd_mcp_enabled) }}
            </span>
          </div>

          <div class="flex items-center justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">OBD port</span>
            <code class="rounded bg-surface-2 px-2 py-0.5 font-mono text-xs text-text">
              {{ config.config.obd_port }}
            </code>
          </div>

          <!-- Live scanner status -->
          <div class="flex items-start justify-between bg-surface px-4 py-3">
            <span class="text-sm text-muted">Scanner status</span>
            <div class="flex items-center gap-2">
              <span class="relative flex h-2 w-2 shrink-0">
                <span
                  class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
                  :class="scanner.status?.scanner_reachable ? 'bg-success' : scanner.status?.available ? 'bg-warning' : 'bg-danger'"
                />
                <span
                  class="relative inline-flex h-2 w-2 rounded-full"
                  :class="scanner.status?.scanner_reachable ? 'bg-success' : scanner.status?.available ? 'bg-warning' : 'bg-danger'"
                />
              </span>
              <span class="font-mono text-xs text-muted">
                {{ scanner.status?.detail ?? '…' }}
              </span>
            </div>
          </div>

        </div>
      </section>

    </template>

  </main>
</template>
