<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="mx-auto flex max-w-2xl flex-col items-center gap-4 px-6 py-24 text-center">
    <p class="font-mono text-6xl font-bold text-accent">404</p>
    <p class="font-mono text-xs uppercase tracking-widest text-muted">Route not found</p>
    <p class="text-muted">That page doesn't exist — it may have moved, or the link is mistyped.</p>
    <RouterLink
      to="/"
      class="mt-2 rounded-card border border-border px-4 py-2 font-mono text-sm text-accent transition-colors hover:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      ‹ Back to Fleet
    </RouterLink>
  </div>
</template>
