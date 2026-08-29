<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { branchesApi, patientsApi } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const branches = ref([])
const patients = ref([])
const patientsError = ref('')

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}

onMounted(async () => {
  try {
    const [branchesRes, patientsRes] = await Promise.all([
      branchesApi.list(),
      patientsApi.list(),
    ])
    branches.value = branchesRes.data
    patients.value = patientsRes.data.results ?? patientsRes.data
  } catch {
    patientsError.value = 'Не удалось загрузить данные.'
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
      <h1 class="text-lg font-semibold text-gray-900">ClinicNet</h1>
      <div class="flex items-center gap-4 text-sm text-gray-600">
        <span>{{ auth.user?.first_name || auth.user?.username }}</span>
        <button class="btn-secondary" @click="logout">Выйти</button>
      </div>
    </header>

    <main class="p-6 max-w-4xl mx-auto space-y-6">
      <section class="card p-4">
        <h2 class="text-sm font-medium text-gray-500 mb-2">Филиалы</h2>
        <div class="flex flex-wrap gap-2">
          <span v-for="branch in branches" :key="branch.id" class="badge-blue">
            {{ branch.name }}
          </span>
        </div>
      </section>

      <section class="card p-4">
        <h2 class="text-sm font-medium text-gray-500 mb-2">Пациенты</h2>
        <p v-if="patientsError" class="text-sm text-red-600">{{ patientsError }}</p>
        <ul v-else class="divide-y divide-gray-100">
          <li v-for="patient in patients" :key="patient.id" class="py-2">
            <RouterLink
              :to="{ name: 'patient-card', params: { id: patient.id } }"
              class="text-primary hover:underline text-sm"
            >
              {{ patient.first_name }} {{ patient.last_name }}
            </RouterLink>
          </li>
        </ul>
      </section>
    </main>
  </div>
</template>
