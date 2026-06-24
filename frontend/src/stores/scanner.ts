import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { ScannerStatus } from '@/api/types'

export const useScannerStore = defineStore('scanner', () => {
  const status = ref<ScannerStatus | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let polling = false

  async function refresh() {
    loading.value = true
    try {
      status.value = await api.getScannerStatus()
    } catch {
      status.value = { available: false, scanner_reachable: false, detail: 'Status unavailable.' }
    } finally {
      loading.value = false
    }
  }

  // Poll the live scanner probe so the UI reflects a scanner being plugged in (or pulled) without
  // a reload. Non-overlapping: the next probe is scheduled only after the previous one resolves.
  function startPolling(intervalMs = 2500) {
    if (polling) return
    polling = true
    const tick = async () => {
      if (!polling) return
      await refresh()
      if (polling) timer = setTimeout(tick, intervalMs)
    }
    void tick()
  }

  function stopPolling() {
    polling = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  return { status, loading, refresh, startPolling, stopPolling }
})
