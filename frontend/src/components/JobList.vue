<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Job } from '@/api/types'

const props = defineProps<{ vehicleId: number }>()
const router = useRouter()
const jobs = ref<Job[]>([])
const title = ref('')
const creating = ref(false)

async function load() {
  jobs.value = await api.listJobs(props.vehicleId)
}

async function add() {
  if (!title.value.trim()) return
  creating.value = true
  try {
    const job = await api.createJob(props.vehicleId, { title: title.value.trim() })
    jobs.value = [job, ...jobs.value]
    title.value = ''
    router.push({ name: 'chat', params: { id: job.id } })
  } finally {
    creating.value = false
  }
}

const statusConfig: Record<string, { cls: string; dot: string }> = {
  open:   { cls: 'text-success border-success/30 bg-success/10', dot: 'bg-success' },
  closed: { cls: 'text-muted border-border bg-surface-2',        dot: 'bg-muted/40' },
}

function formatDate(utc: string): string {
  const date = new Date(utc)
  return isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

onMounted(load)
</script>

<template>
  <section>
    <!-- Section header -->
    <div class="mb-4 flex items-center gap-3">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
        class="h-4 w-4 text-accent" aria-hidden="true">
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
      </svg>
      <h2 class="font-mono text-xs font-semibold uppercase tracking-widest text-muted">
        Jobs
      </h2>
      <span v-if="jobs.length" class="ml-auto font-mono text-xs text-muted/60">
        {{ jobs.length }}
      </span>
    </div>

    <!-- New job form -->
    <form class="mb-4 flex gap-2" @submit.prevent="add">
      <input
        v-model="title"
        aria-label="Describe the issue"
        placeholder="Describe the issue (e.g. Oil leak)"
        class="flex-1 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-muted/60 transition-colors duration-150 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40"
      />
      <button
        type="submit"
        :disabled="!title.trim() || creating"
        class="flex shrink-0 items-center gap-1.5 rounded-md bg-accent px-4 py-2 font-mono text-sm font-semibold text-bg transition-opacity duration-150 hover:opacity-90 disabled:opacity-40"
      >
        <svg v-if="creating" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          class="h-3.5 w-3.5 animate-spin" aria-hidden="true">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        <span>{{ creating ? 'Starting…' : '+ Start' }}</span>
      </button>
    </form>

    <!-- Jobs list -->
    <div v-if="jobs.length === 0" class="rounded-card border border-dashed border-border px-4 py-6 text-center">
      <p class="font-mono text-xs text-muted/50">No jobs yet — start one above to begin a chat session</p>
    </div>
    <ul v-else class="space-y-1.5">
      <li v-for="j in jobs" :key="j.id">
        <RouterLink
          :to="{ name: 'chat', params: { id: j.id } }"
          class="group flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2.5 transition-all duration-150 hover:border-accent/30 hover:bg-surface-2"
        >
          <!-- Wrench icon -->
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
            class="h-4 w-4 shrink-0 text-muted/50 transition-colors duration-150 group-hover:text-accent/70"
            aria-hidden="true">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
          </svg>

          <!-- Title + date -->
          <div class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium text-text">{{ j.title }}</span>
            <span class="font-mono text-xs text-muted/60">{{ formatDate(j.created_utc) }}</span>
          </div>

          <!-- Status pill -->
          <span
            v-if="statusConfig[j.status]"
            class="flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-xs font-medium"
            :class="statusConfig[j.status].cls"
          >
            <span class="h-1.5 w-1.5 rounded-full" :class="statusConfig[j.status].dot" />
            {{ j.status }}
          </span>
          <span v-else class="font-mono text-xs text-muted">{{ j.status }}</span>

          <!-- Chevron -->
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            class="h-4 w-4 shrink-0 text-muted/30 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-accent"
            aria-hidden="true">
            <path d="m9 18 6-6-6-6"/>
          </svg>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
