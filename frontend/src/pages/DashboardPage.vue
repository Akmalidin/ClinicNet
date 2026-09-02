<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { branchesApi, patientsApi } from '../api'
import ReferralQueueWidget from '../components/referrals/ReferralQueueWidget.vue'
import TriageQueueWidget from '../components/triage/TriageQueueWidget.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const branches = ref([])
const branchesError = ref('')
const patients = ref([])
const patientsError = ref('')

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}

// Fetched independently, not via one Promise.all: branch.view and
// patient.view are separate RBAC grants (same class of bug as
// PatientCardPage.vue's patient/visits split — audited the whole
// frontend for this pattern while starting Phase 3, per the explicit
// ask to check systemically rather than wait for it to resurface on a
// new role). Every current role happens to hold both together, but
// Phase 3's cashier role is exactly the kind of narrowly-scoped grant
// that could hold one without the other.
async function loadBranches() {
  branchesError.value = ''
  try {
    const { data } = await branchesApi.list()
    branches.value = data
  } catch {
    branchesError.value = 'Филиалы недоступны (недостаточно прав или ошибка загрузки).'
  }
}

async function loadPatients() {
  patientsError.value = ''
  try {
    const { data } = await patientsApi.list()
    patients.value = data.results ?? data
  } catch {
    patientsError.value = 'Пациенты недоступны (недостаточно прав или ошибка загрузки).'
  }
}

onMounted(() => {
  loadBranches()
  loadPatients()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
      <h1 class="text-lg font-semibold text-gray-900">ClinicNet</h1>
      <div class="flex items-center gap-4 text-sm text-gray-600">
        <RouterLink :to="{ name: 'network-dashboard' }" class="text-primary hover:underline">Дашборд сети</RouterLink>
        <RouterLink :to="{ name: 'schedule' }" class="text-primary hover:underline">Расписание</RouterLink>
        <RouterLink :to="{ name: 'network-schedule' }" class="text-primary hover:underline">Расписание (сеть)</RouterLink>
        <RouterLink
          v-if="auth.churnBranches.length"
          :to="{ name: 'churn-alerts' }"
          class="text-primary hover:underline"
        >
          Отток
        </RouterLink>
        <RouterLink
          v-if="auth.inventoryBranches.length"
          :to="{ name: 'warehouse-stock' }"
          class="text-primary hover:underline"
        >
          Склад
        </RouterLink>
        <RouterLink
          v-if="auth.triageBranches.length"
          :to="{ name: 'triage-queue' }"
          class="text-primary hover:underline"
        >
          Триаж
        </RouterLink>
        <RouterLink
          v-if="auth.bedBoardDepartments.length"
          :to="{ name: 'bed-management' }"
          class="text-primary hover:underline"
        >
          Койки
        </RouterLink>
        <RouterLink
          v-if="auth.roles.some((r) => r.role === 'Администратор сети')"
          :to="{ name: 'rbac-admin' }"
          class="text-primary hover:underline"
        >
          Роли и доступ
        </RouterLink>
        <RouterLink
          v-if="auth.roles.some((r) => r.role === 'Администратор сети')"
          :to="{ name: 'staff-hr' }"
          class="text-primary hover:underline"
        >
          Персонал
        </RouterLink>
        <span>{{ auth.user?.first_name || auth.user?.username }}</span>
        <button class="btn-secondary" @click="logout">Выйти</button>
      </div>
    </header>

    <main class="p-6 max-w-4xl mx-auto space-y-6">
      <section class="card p-4">
        <h2 class="text-sm font-medium text-gray-500 mb-2">Филиалы</h2>
        <p v-if="branchesError" class="text-sm text-red-600">{{ branchesError }}</p>
        <div v-else class="flex flex-wrap gap-2">
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

      <section>
        <h2 class="text-sm font-medium text-gray-500 mb-2">Очередь направлений (сеть)</h2>
        <!-- No `branch` prop -> network-wide, per whatever this user's
             referral_branches (+ "own") actually cover. Same widget on a
             branch dashboard would pass :branch="currentBranchId". -->
        <ReferralQueueWidget />
      </section>

      <section v-if="auth.triageBranches.length">
        <!-- Guarded on the client, not just left to render an empty
             queue: a user without triage.view anywhere shouldn't even
             fire GET /triage-suggestions/ (it would just come back 403) —
             same requirement as ReferralQueueWidget, made explicit for
             this one because the AI-триаж manual test checklist calls
             it out directly (frontend prompt, "RBAC" section). -->
        <h2 class="text-sm font-medium text-gray-500 mb-2">
          Очередь AI-триажа (сеть) —
          <RouterLink :to="{ name: 'triage-queue' }" class="text-primary hover:underline">
            открыть полную очередь
          </RouterLink>
        </h2>
        <TriageQueueWidget />
      </section>
    </main>
  </div>
</template>
