<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { patientsApi, visitsApi } from '../api'
import ReferralModal from '../components/referrals/ReferralModal.vue'

const props = defineProps({ id: { type: [String, Number], required: true } })

const patient = ref(null)
const visits = ref([])
const loadError = ref('')

const modalOpen = ref(false)
const activeVisit = ref(null)
const justCreated = ref(null)

async function load() {
  loadError.value = ''
  try {
    const [patientRes, visitsRes] = await Promise.all([
      patientsApi.get(props.id),
      visitsApi.list({ patient: props.id }),
    ])
    patient.value = patientRes.data
    visits.value = visitsRes.data.results ?? visitsRes.data
  } catch {
    loadError.value = 'Не удалось загрузить карту пациента.'
  }
}
onMounted(load)

function openReferral(visit) {
  activeVisit.value = visit
  justCreated.value = null
  modalOpen.value = true
}

function onCreated(referral) {
  justCreated.value = referral
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
      <RouterLink :to="{ name: 'dashboard' }" class="text-sm text-gray-500 hover:text-gray-700">
        ← Пациенты
      </RouterLink>
      <h1 v-if="patient" class="text-lg font-semibold text-gray-900">
        {{ patient.first_name }} {{ patient.last_name }}
      </h1>
    </header>

    <main class="p-6 max-w-3xl mx-auto space-y-6">
      <p v-if="loadError" class="text-sm text-red-600">{{ loadError }}</p>

      <div v-if="justCreated" class="card p-4 border-accent bg-green-50 text-sm text-green-800">
        Направление создано и отправлено врачу (статус: {{ justCreated.status }}).
      </div>

      <section v-if="patient" class="card p-4 space-y-1 text-sm text-gray-600">
        <p v-if="patient.phone">Телефон: {{ patient.phone }}</p>
        <p v-if="patient.date_of_birth">Дата рождения: {{ patient.date_of_birth }}</p>
        <p v-if="patient.notes">{{ patient.notes }}</p>
      </section>

      <section class="card p-4">
        <h2 class="text-sm font-medium text-gray-500 mb-3">Приёмы (осмотры)</h2>
        <ul class="divide-y divide-gray-100">
          <li v-for="visit in visits" :key="visit.id" class="py-3 flex items-center justify-between gap-4">
            <div>
              <p class="text-sm text-gray-900">{{ visit.reason }}</p>
              <p class="text-xs text-gray-500">
                {{ visit.branch_name }} · {{ visit.doctor_name }} ·
                <span class="badge-gray">{{ visit.status }}</span>
              </p>
            </div>
            <button class="btn-secondary shrink-0" @click="openReferral(visit)">Направить →</button>
          </li>
        </ul>
        <p v-if="visits.length === 0" class="text-sm text-gray-400">Приёмов пока нет.</p>
      </section>
    </main>

    <ReferralModal
      v-if="activeVisit"
      :open="modalOpen"
      :patient="patient"
      :visit="activeVisit"
      @close="modalOpen = false"
      @created="onCreated"
    />
  </div>
</template>
