<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import { streamChatMessage, type ChatStreamEvent } from '@/api/chatStream'
import type { ChatMessage } from '@/api/types'
import ToolChip from '@/components/ToolChip.vue'
import MessageBubble from '@/components/MessageBubble.vue'

interface Turn {
  role: string
  content: string
  sources: Array<Record<string, unknown>> | null
}

const route = useRoute()
const jobId = Number(route.params.id)
const turns = ref<Turn[]>([])
const draft = ref('')
const streaming = ref(false)
const activeTools = ref<{ name: string; done: boolean }[]>([])
const scrollAnchor = ref<HTMLElement | null>(null)

function scrollBottom() {
  nextTick(() => {
    if (typeof scrollAnchor.value?.scrollIntoView === 'function') {
      scrollAnchor.value.scrollIntoView({ behavior: 'smooth' })
    }
  })
}

onMounted(async () => {
  const history: ChatMessage[] = await api.listMessages(jobId)
  turns.value = history.map((m) => ({ role: m.role, content: m.content, sources: m.sources_json }))
  scrollBottom()
})

watch(() => turns.value.length, scrollBottom)

async function send() {
  const content = draft.value.trim()
  if (!content || streaming.value) return
  draft.value = ''
  turns.value.push({ role: 'user', content, sources: null })
  const assistant: Turn = { role: 'assistant', content: '', sources: null }
  turns.value.push(assistant)
  streaming.value = true
  activeTools.value = []
  scrollBottom()

  try {
    await streamChatMessage(jobId, content, (e: ChatStreamEvent) => {
      if (e.type === 'token') {
        assistant.content += e.text
        scrollBottom()
      } else if (e.type === 'tool_call') {
        activeTools.value.push({ name: e.name, done: false })
      } else if (e.type === 'tool_result') {
        const chip = activeTools.value.find((t) => t.name === e.name && !t.done)
        if (chip) chip.done = true
      } else if (e.type === 'sources') {
        assistant.sources = e.sources
      } else if (e.type === 'error') {
        assistant.content += `\n[error] ${e.detail}`
      }
    })
  } catch (err) {
    assistant.content += `\n[connection error] ${(err as Error).message}`
  } finally {
    streaming.value = false
  }
}
</script>

<template>
  <main class="flex h-[calc(100vh-3.25rem)] flex-col bg-bg">

    <!-- Transcript -->
    <div class="flex-1 overflow-y-auto px-4 py-6 scroll-smooth" aria-live="polite" aria-label="Chat transcript">
      <div class="mx-auto max-w-2xl">

        <!-- Empty state -->
        <div v-if="turns.length === 0" class="flex flex-col items-center justify-center py-20 text-center">
          <div class="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-surface text-accent">
            <!-- Wrench icon -->
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6" aria-hidden="true">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
            </svg>
          </div>
          <p class="font-mono text-xs uppercase tracking-widest text-muted/50">Ready to diagnose</p>
          <p class="mt-1 text-sm text-muted/40">Ask anything about this vehicle</p>
        </div>

        <!-- Message bubbles -->
        <MessageBubble
          v-for="(t, i) in turns"
          :key="i"
          :role="t.role"
          :content="t.content"
          :sources="t.sources"
        />

        <!-- Tool activity row — shown while tools are active -->
        <div v-if="activeTools.length" class="mb-4 flex flex-wrap items-center gap-1.5 pl-1">
          <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/40">tools</span>
          <ToolChip v-for="(tool, i) in activeTools" :key="i" :name="tool.name" :active="!tool.done" />
        </div>

        <!-- Streaming indicator pulse when no text yet -->
        <div v-if="streaming && turns.at(-1)?.content === ''" class="mb-4 flex items-center gap-2 pl-1">
          <span class="h-1.5 w-1.5 rounded-full bg-accent animate-ping" />
          <span class="font-mono text-xs text-muted/50 tracking-wide">thinking…</span>
        </div>

        <!-- Scroll anchor -->
        <div ref="scrollAnchor" aria-hidden="true" />
      </div>
    </div>

    <!-- Composer -->
    <div class="border-t border-border bg-surface px-4 py-3">
      <form class="mx-auto flex max-w-2xl items-end gap-2" @submit.prevent="send">
        <div class="relative flex-1">
          <textarea
            v-model="draft"
            rows="2"
            aria-label="Message"
            placeholder="Ask about this vehicle…"
            :disabled="streaming"
            class="w-full resize-none rounded-xl border border-border bg-bg px-3.5 py-2.5 font-sans text-sm text-text placeholder-muted/40 outline-none transition-colors duration-150 focus:border-accent/50 focus:ring-1 focus:ring-accent/20 disabled:opacity-50"
            @keydown.enter.exact.prevent="send"
          />
        </div>
        <button
          type="submit"
          :disabled="streaming || !draft.trim()"
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-bg shadow-sm transition-all duration-150 hover:bg-accent-strong active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="Send message"
        >
          <!-- Send arrow icon -->
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4" aria-hidden="true">
            <path d="m22 2-7 20-4-9-9-4 20-7z"/>
          </svg>
        </button>
      </form>
    </div>

  </main>
</template>
