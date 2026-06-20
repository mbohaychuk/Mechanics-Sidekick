<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import type { Document } from '@/api/types'

const props = defineProps<{ vehicleId: number }>()
const documents = ref<Document[]>([])
const uploading = ref(false)
const dragOver = ref(false)
const timers = new Map<number, ReturnType<typeof setInterval>>()

async function load() {
  documents.value = await api.listDocuments(props.vehicleId)
  documents.value.filter((d) => d.processing_status === 'pending').forEach(poll)
}

function poll(doc: Document) {
  if (timers.has(doc.id)) return
  const timer = setInterval(async () => {
    const fresh = await api.getDocument(doc.id)
    const i = documents.value.findIndex((d) => d.id === fresh.id)
    if (i !== -1) documents.value[i] = fresh
    if (fresh.processing_status !== 'pending') {
      clearInterval(timer)
      timers.delete(doc.id)
    }
  }, 2000)
  timers.set(doc.id, timer)
}

async function upload(files: FileList | null) {
  if (!files?.length) return
  uploading.value = true
  try {
    for (const file of Array.from(files)) {
      const doc = await api.uploadDocument(props.vehicleId, file)
      documents.value = [doc, ...documents.value]
      poll(doc)
    }
  } finally {
    uploading.value = false
  }
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  upload(e.dataTransfer?.files ?? null)
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  dragOver.value = true
}

function onDragLeave() {
  dragOver.value = false
}

const statusConfig: Record<string, { label: string; cls: string; dot: string }> = {
  ready:   { label: 'READY',   cls: 'text-success border-success/30 bg-success/10',   dot: 'bg-success' },
  failed:  { label: 'FAILED',  cls: 'text-danger border-danger/30 bg-danger/10',      dot: 'bg-danger' },
  pending: { label: 'INDEXING', cls: 'text-warning border-warning/30 bg-warning/10',  dot: 'bg-warning animate-pulse' },
  no_text: { label: 'NO TEXT', cls: 'text-danger border-danger/30 bg-danger/10',      dot: 'bg-danger' },
}

function docTypeLabel(t: string) {
  return t.replace(/_/g, ' ')
}

onMounted(load)
onUnmounted(() => timers.forEach((t) => clearInterval(t)))
</script>

<template>
  <section>
    <!-- Section header -->
    <div class="mb-4 flex items-center gap-3">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
        class="h-4 w-4 text-accent" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
      <h2 class="font-mono text-xs font-semibold uppercase tracking-widest text-muted">
        Documents
      </h2>
      <span v-if="documents.length" class="ml-auto font-mono text-xs text-muted/60">
        {{ documents.length }}
      </span>
    </div>

    <!-- Drop zone -->
    <label
      class="mb-4 block cursor-pointer rounded-card border-2 border-dashed transition-all duration-200"
      :class="dragOver
        ? 'border-accent bg-accent/5 scale-[1.01]'
        : 'border-border bg-surface hover:border-accent/40 hover:bg-surface-2'"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <div class="flex flex-col items-center gap-2 px-6 py-8 text-center">
        <!-- Upload icon -->
        <div class="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-surface-2 transition-colors duration-200"
          :class="dragOver ? 'border-accent/60 bg-accent/10' : ''">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
            class="h-5 w-5 transition-colors duration-200"
            :class="dragOver ? 'text-accent' : 'text-muted'"
            aria-hidden="true">
            <polyline points="16 16 12 12 8 16"/>
            <line x1="12" y1="12" x2="12" y2="21"/>
            <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
          </svg>
        </div>
        <div>
          <p class="text-sm font-medium text-text">
            <span v-if="dragOver" class="text-accent">Drop PDF here</span>
            <span v-else>Drag a PDF, or <span class="text-accent underline decoration-dashed underline-offset-2">browse</span></span>
          </p>
          <p class="mt-0.5 font-mono text-xs text-muted/60">Service manuals, repair guides, TSBs</p>
        </div>
        <p v-if="uploading" class="mt-1 flex items-center gap-2 font-mono text-xs text-accent">
          <span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          Uploading…
        </p>
      </div>
      <input type="file" accept="application/pdf" class="sr-only" multiple
        @change="upload(($event.target as HTMLInputElement).files)" />
    </label>

    <!-- Document list -->
    <div v-if="documents.length === 0" class="rounded-card border border-dashed border-border px-4 py-6 text-center">
      <p class="font-mono text-xs text-muted/50">No documents — drop a service manual above</p>
    </div>
    <ul v-else class="space-y-1.5">
      <li
        v-for="d in documents"
        :key="d.id"
        class="group flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2.5 transition-colors duration-150 hover:border-border hover:bg-surface-2"
      >
        <!-- PDF icon -->
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
          class="h-4 w-4 shrink-0 text-muted/50" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>

        <!-- Filename + type -->
        <div class="min-w-0 flex-1">
          <span class="block truncate font-mono text-sm text-text">{{ d.file_name }}</span>
          <span class="font-mono text-xs capitalize text-muted/60">{{ docTypeLabel(d.document_type) }}</span>
        </div>

        <!-- Status pill -->
        <span
          v-if="statusConfig[d.processing_status]"
          class="flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-xs font-medium"
          :class="statusConfig[d.processing_status].cls"
        >
          <span class="h-1.5 w-1.5 rounded-full" :class="statusConfig[d.processing_status].dot" />
          {{ statusConfig[d.processing_status].label }}
        </span>
        <span v-else class="font-mono text-xs text-muted">{{ d.processing_status }}</span>
      </li>
    </ul>
  </section>
</template>
