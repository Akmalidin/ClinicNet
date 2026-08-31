<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { patientsApi, visitsApi } from '../api'
import LabOrderModal from '../components/diagnostics/LabOrderModal.vue'
import LabOrdersSection from '../components/diagnostics/LabOrdersSection.vue'
import ReferralModal from '../components/referrals/ReferralModal.vue'

const props = defineProps({ id: { type: [String, Number], required: true } })

const patient = ref(null)
const visits = ref([])
const patientError = ref('')
const visitsError = ref('')

const modalOpen = ref(false)
const activeVisit = ref(null)
const justCreated = ref(null)

const labOrderModalOpen = ref(false)
const activeLabOrderVisit = ref(null)
const labOrdersSection = ref(null)
const labOrderJustCreated = ref(false)

// Patient and visits are fetched (and can fail) independently rather than
// via one Promise.all — visit.view and patient.view are separate RBAC
// grants (a receptionist has the former without the latter, in this
// project's own seed_rbac), so a user without visit.view must still see
// the patient's demographics instead of the whole card going blank behind
// one shared error. Found via manual RBAC verification, not by inspection.
async function loadPatient() {
  patientError.value = ''
  try {
    const { data } = await patientsApi.get(props.id)
    patient.value = data
  } catch {
    patientError.value = 'Не удалось загрузить карточку пациента.'
  }
}

async function loadVisits() {
  visitsError.value = ''
  try {
    const { data } = await visitsApi.list({ patient: props.id })
    visits.value = data.results ?? data
  } catch {
    visitsError.value = 'Приёмы недоступны (недостаточно прав или ошибка загрузки).'
  }
}

onMounted(() => {
  loadPatient()
  loadVisits()
})

function openReferral(visit) {
  activeVisit.value = visit
  justCreated.value = null
  modalOpen.value = true
}

function onCreated(referral) {
  justCreated.value = referral
}

function openLabOrder(visit) {
  activeLabOrderVisit.value = visit
  labOrderJustCreated.value = false
  labOrderModalOpen.value = true
}

async function onLabOrderCreated() {
  labOrderJustCreated.value = true
  await labOrdersSection.value?.load()
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
      <p v-if="patientError" class="text-sm text-red-600">{{ patientError }}</p>

      <div v-if="justCreated" class="card p-4 border-accent bg-green-50 text-sm text-green-800">
        Направление создано и отправлено врачу (статус: {{ justCreated.status }}).
      </div>
      <div v-if="labOrderJustCreated" class="card p-4 border-accent bg-green-50 text-sm text-green-800">
        Анализ заказан.
      </div>

      <section v-if="patient" class="card p-4 space-y-1 text-sm text-gray-600">
        <p v-if="patient.phone">Телефон: {{ patient.phone }}</p>
        <p v-if="patient.date_of_birth">Дата рождения: {{ patient.date_of_birth }}</p>
        <p v-if="patient.notes">{{ patient.notes }}</p>
      </section>

      <section class="card p-4">
        <h2 class="text-sm font-medium text-gray-500 mb-3">Приёмы (осмотры)</h2>
        <p v-if="visitsError" class="text-sm text-red-600">{{ visitsError }}</p>
        <template v-else>
          <ul class="divide-y divide-gray-100">
            <li v-for="visit in visits" :key="visit.id" class="py-3 flex items-center justify-between gap-4">
              <div>
                <p class="text-sm text-gray-900">{{ visit.reason }}</p>
                <p class="text-xs text-gray-500">
                  {{ visit.branch_name }} · {{ visit.doctor_name }} ·
                  <span class="badge-gray">{{ visit.status }}</span>
                </p>
              </div>
              <div class="shrink-0 flex gap-1">
                <button class="btn-secondary" @click="openLabOrder(visit)">Заказать анализ</button>
                <button class="btn-secondary" @click="openReferral(visit)">Направить →</button>
              </div>
            </li>
          </ul>
          <p v-if="visits.length === 0" class="text-sm text-gray-400">Приёмов пока нет.</p>
        </template>
      </section>

      <LabOrdersSection v-if="patient" ref="labOrdersSection" :patient-id="id" />
    </main>

    <ReferralModal
      v-if="activeVisit"
      :open="modalOpen"
      :patient="patient"
      :visit="activeVisit"
      @close="modalOpen = false"
      @created="onCreated"
    />
    <LabOrderModal
      v-if="activeLabOrderVisit"
      :open="labOrderModalOpen"
      :patient="patient"
      :visit="activeLabOrderVisit"
      @close="labOrderModalOpen = false"
      @created="onLabOrderCreated"
    />
  </div>
</template>
