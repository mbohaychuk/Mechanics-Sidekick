<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { Vehicle } from '@/api/types'
import DocumentList from '@/components/DocumentList.vue'
import JobList from '@/components/JobList.vue'

const route = useRoute()
const vehicleId = Number(route.params.id)
const vehicle = ref<Vehicle | null>(null)

onMounted(async () => {
  vehicle.value = await api.getVehicle(vehicleId)
})
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-8">

    <!-- Back nav -->
    <RouterLink
      to="/"
      class="group mb-6 inline-flex items-center gap-1.5 font-mono text-xs text-muted/60 transition-colors duration-150 hover:text-muted"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        class="h-3.5 w-3.5 transition-transform duration-150 group-hover:-translate-x-0.5"
        aria-hidden="true">
        <path d="m15 18-6-6 6-6"/>
      </svg>
      Fleet
    </RouterLink>

    <!-- Vehicle header — skeleton while loading -->
    <div v-if="!vehicle" class="mb-8 animate-pulse">
      <div class="h-7 w-56 rounded-md bg-surface-2" />
      <div class="mt-2 h-4 w-32 rounded bg-surface-2" />
    </div>
    <div v-else class="mb-8">
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <!-- Year badge -->
        <span class="font-mono text-base font-medium text-accent">{{ vehicle.year }}</span>
        <!-- Make + model -->
        <h1 class="text-2xl font-semibold tracking-tight text-text">
          {{ vehicle.make }} {{ vehicle.model }}
        </h1>
        <!-- Engine spec -->
        <span v-if="vehicle.engine" class="font-mono text-sm text-muted">
          {{ vehicle.engine }}
        </span>
      </div>
      <!-- VIN line -->
      <p v-if="vehicle.vin" class="mt-1 font-mono text-xs text-muted/60">
        VIN&nbsp;<span class="tracking-widest">{{ vehicle.vin }}</span>
      </p>
      <!-- Notes line -->
      <p v-if="vehicle.notes" class="mt-2 max-w-prose text-sm text-muted">
        {{ vehicle.notes }}
      </p>
      <!-- Live telemetry entry -->
      <RouterLink
        :to="{ name: 'live', params: { id: vehicleId } }"
        class="mt-3 inline-flex items-center gap-1.5 rounded bg-surface-2 px-3 py-1.5 font-mono text-xs text-accent hover:bg-surface"
      >
        ● Live data
      </RouterLink>
    </div>

    <!-- Divider with label -->
    <div class="mb-6 flex items-center gap-3">
      <div class="h-px flex-1 bg-border" />
      <span class="font-mono text-xs text-muted/40 uppercase tracking-widest">Workshop</span>
      <div class="h-px flex-1 bg-border" />
    </div>

    <!-- Two-column panel grid -->
    <div class="grid gap-6 md:grid-cols-2">
      <!-- Documents panel -->
      <div class="rounded-card border border-border bg-surface p-5">
        <DocumentList :vehicle-id="vehicleId" />
      </div>

      <!-- Jobs panel -->
      <div class="rounded-card border border-border bg-surface p-5">
        <JobList :vehicle-id="vehicleId" />
      </div>
    </div>

  </main>
</template>
