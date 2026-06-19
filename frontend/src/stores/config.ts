import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { AppConfig } from '@/api/types'

export const useConfigStore = defineStore('config', () => {
  const config = ref<AppConfig | null>(null)

  async function load() {
    config.value = await api.getConfig()
  }

  return { config, load }
})
