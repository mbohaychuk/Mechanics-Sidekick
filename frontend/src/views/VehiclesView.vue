<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useVehiclesStore } from '@/stores/vehicles'

const store = useVehiclesStore()
const router = useRouter()
const form = reactive({ year: new Date().getFullYear(), make: '', model: '', engine: '' })

onMounted(() => store.load())

async function add() {
  if (!form.make || !form.model) return
  const vehicle = await store.create({ ...form })
  form.make = ''; form.model = ''; form.engine = ''
  router.push({ name: 'vehicle', params: { id: vehicle.id } })
}

function open(id: number) {
  store.select(id)
  router.push({ name: 'vehicle', params: { id } })
}
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-8">

    <!-- Page header -->
    <div class="mb-8 flex items-baseline justify-between">
      <div>
        <h1 class="font-mono text-2xl font-semibold tracking-tight text-text">
          Fleet
        </h1>
        <p class="mt-1 text-sm text-muted">
          {{ store.vehicles.length }} vehicle{{ store.vehicles.length !== 1 ? 's' : '' }} registered
        </p>
      </div>
    </div>

    <!-- Add-vehicle form -->
    <section class="mb-8 rounded-card border border-border bg-surface p-5">
      <h2 class="mb-4 font-mono text-xs font-semibold uppercase tracking-widest text-muted">
        Register Vehicle
      </h2>
      <form class="grid grid-cols-2 gap-3 sm:grid-cols-5" @submit.prevent="add">
        <input
          v-model.number="form.year"
          type="number"
          aria-label="Year"
          placeholder="Year"
          min="1900"
          :max="new Date().getFullYear() + 1"
          class="col-span-1 rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <input
          v-model="form.make"
          aria-label="Make"
          placeholder="Make"
          required
          class="col-span-1 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <input
          v-model="form.model"
          aria-label="Model"
          placeholder="Model"
          required
          class="col-span-1 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <input
          v-model="form.engine"
          aria-label="Engine"
          placeholder="Engine"
          class="col-span-1 rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          type="submit"
          class="col-span-2 rounded-md bg-accent px-4 py-2 font-mono text-sm font-semibold text-bg transition-opacity duration-150 hover:opacity-90 disabled:opacity-40 sm:col-span-1"
          :disabled="!form.make || !form.model"
        >
          + Add
        </button>
      </form>
    </section>

    <!-- Loading state -->
    <p v-if="store.loading" class="py-8 text-center font-mono text-sm text-muted">
      Loading…
    </p>

    <!-- Error state -->
    <p v-else-if="store.error" class="rounded-card border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
      {{ store.error }}
    </p>

    <!-- Empty state -->
    <div
      v-else-if="store.vehicles.length === 0"
      class="flex flex-col items-center justify-center rounded-card border border-dashed border-border py-16 text-center"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="mb-3 h-10 w-10 text-muted/40"
        aria-hidden="true"
      >
        <rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h4l3 3v5h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>
      </svg>
      <p class="text-sm font-medium text-muted">No vehicles yet</p>
      <p class="mt-1 text-xs text-muted/60">Register one above to get started.</p>
    </div>

    <!-- Vehicle list -->
    <ul v-else class="space-y-2">
      <li v-for="v in store.vehicles" :key="v.id">
        <button
          class="group w-full rounded-card border border-border bg-surface px-5 py-4 text-left transition-all duration-150 hover:border-accent/40 hover:bg-surface-2"
          @click="open(v.id)"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-baseline gap-3">
              <!-- Year badge -->
              <span class="font-mono text-sm font-medium text-accent">{{ v.year }}</span>
              <!-- Make + model -->
              <span class="font-semibold text-text">{{ v.make }} {{ v.model }}</span>
              <!-- Engine spec -->
              <span v-if="v.engine" class="font-mono text-sm text-muted">{{ v.engine }}</span>
            </div>
            <!-- Chevron -->
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-4 w-4 text-muted/40 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-accent"
              aria-hidden="true"
            >
              <path d="m9 18 6-6-6-6"/>
            </svg>
          </div>
          <div v-if="v.vin" class="mt-1 font-mono text-xs text-muted/60">
            VIN {{ v.vin }}
          </div>
        </button>
      </li>
    </ul>

  </main>
</template>
