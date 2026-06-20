<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
  <div class="flex items-start gap-2 px-4 py-2">
    <span class="mt-1 text-accent/60 select-none" aria-hidden="true">▸</span>
    <p class="text-sm leading-relaxed text-text/90">{{ text }}</p>
  </div>
</template>
