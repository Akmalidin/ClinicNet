<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import LoadingOverlay from './components/LoadingOverlay.vue'
import { useAuthStore } from './stores/auth'
import { useLoadingStore } from './stores/loading'

const auth = useAuthStore()
const loading = useLoadingStore()
const router = useRouter()

function handleAuthFailure() {
  auth.logout()
  router.push({ name: 'login' })
}

// auth.restore() already ran in main.js before the router/app were even
// installed (see its comment there) — this only wires the "session died
// mid-session" path (a refresh call failing in api/client.js).
onMounted(() => {
  window.addEventListener('clinicnet:auth-failure', handleAuthFailure)
})
onBeforeUnmount(() => {
  window.removeEventListener('clinicnet:auth-failure', handleAuthFailure)
})
</script>

<template>
  <LoadingOverlay :active="loading.isLoading" />
  <RouterView />
</template>
