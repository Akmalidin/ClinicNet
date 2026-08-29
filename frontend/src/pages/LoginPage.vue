<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.push(route.query.redirect || { name: 'dashboard' })
  } catch (e) {
    error.value =
      e.response?.data?.detail || 'Не удалось войти. Проверьте логин и пароль.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50">
    <form class="card w-full max-w-sm p-8 space-y-4" @submit.prevent="submit">
      <h1 class="text-xl font-semibold text-gray-900">ClinicNet</h1>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Логин</label>
        <input v-model="username" class="form-input" autocomplete="username" required />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Пароль</label>
        <input
          v-model="password"
          type="password"
          class="form-input"
          autocomplete="current-password"
          required
        />
      </div>

      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

      <button type="submit" class="btn-primary w-full" :disabled="submitting">
        {{ submitting ? 'Входим…' : 'Войти' }}
      </button>
    </form>
  </div>
</template>
