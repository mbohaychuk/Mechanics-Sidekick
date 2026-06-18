import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { ScannerStatus } from '@/api/types'

export const useScannerStore = defineStore('scanner', () => {
  const status = ref<ScannerStatus | null>(null)
  const loading = ref(false)

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

  return { status, loading, refresh }
})
