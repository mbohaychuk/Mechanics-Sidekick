import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { Vehicle, VehicleCreate } from '@/api/types'

export const useVehiclesStore = defineStore('vehicles', () => {
  const vehicles = ref<Vehicle[]>([])
  const selectedId = ref<number | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const selected = computed(() => vehicles.value.find((v) => v.id === selectedId.value) ?? null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      vehicles.value = await api.listVehicles()
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function create(body: VehicleCreate): Promise<Vehicle> {
    const vehicle = await api.createVehicle(body)
    vehicles.value = [vehicle, ...vehicles.value]
    return vehicle
  }

  function select(id: number) {
    selectedId.value = id
  }

  return { vehicles, selectedId, loading, error, selected, load, create, select }
})
