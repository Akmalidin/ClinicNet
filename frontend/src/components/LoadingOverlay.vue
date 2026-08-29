<script setup>
// A thin top-of-screen progress bar rather than a blocking spinner overlay
// — in-flight requests shouldn't freeze the UI, just make it visible that
// something's happening (per the "при загрузке — анимация загрузки"
// requirement). Driven by stores/loading.js, which api/client.js bumps
// around every request.
defineProps({ active: { type: Boolean, default: false } })
</script>

<template>
  <div
    class="fixed top-0 left-0 right-0 h-1 z-50 overflow-hidden transition-opacity duration-200"
    :class="active ? 'opacity-100' : 'opacity-0'"
    aria-hidden="true"
  >
    <div class="h-full w-1/3 bg-primary animate-[loading-bar_1s_ease-in-out_infinite]" />
  </div>
</template>

<style scoped>
@keyframes loading-bar {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(300%); }
}
</style>
