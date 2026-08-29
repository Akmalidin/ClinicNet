<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { appointmentsApi } from '../api'
import ReferralBadge from '../components/referrals/ReferralBadge.vue'

const appointments = ref([])
const loadError = ref('')

const statusBadge = {
  scheduled: 'badge-blue',
  confirmed: 'badge-blue',
  in_progress: 'badge-yellow',
  completed: 'badge-green',
  cancelled: 'badge-gray',
  no_show: 'badge-red',
}

function formatDateTime(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(async () => {
  try {
    const { data } = await appointmentsApi.list()
    const rows = data.results ?? data
    appointments.value = [...rows].sort((a, b) => a.starts_at.localeCompare(b.starts_at))
  } catch {
    loadError.value = 'Не удалось загрузить расписание.'
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
      <RouterLink :to="{ name: 'dashboard' }" class="text-sm text-gray-500 hover:text-gray-700">
        ← Дашборд
      </RouterLink>
      <h1 class="text-lg font-semibold text-gray-900">Расписание</h1>
    </header>

    <main class="p-6 max-w-4xl mx-auto">
      <p v-if="loadError" class="text-sm text-red-600">{{ loadError }}</p>
      <div v-else class="card overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="border-b border-gray-100 text-left text-gray-500">
            <tr>
              <th class="px-4 py-2 font-medium">Время</th>
              <th class="px-4 py-2 font-medium">Пациент</th>
              <th class="px-4 py-2 font-medium">Врач</th>
              <th class="px-4 py-2 font-medium">Филиал</th>
              <th class="px-4 py-2 font-medium">Статус</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            <tr v-for="appt in appointments" :key="appt.id">
              <td class="px-4 py-2 whitespace-nowrap">
                {{ formatDateTime(appt.starts_at) }}–{{ formatDateTime(appt.ends_at).slice(-5) }}
              </td>
              <td class="px-4 py-2">
                {{ appt.patient_display }}
                <ReferralBadge :referral="appt.referral" />
              </td>
              <td class="px-4 py-2 text-gray-500">{{ appt.doctor_display }}</td>
              <td class="px-4 py-2 text-gray-500">{{ appt.branch_display }}</td>
              <td class="px-4 py-2">
                <span :class="statusBadge[appt.status] ?? 'badge-gray'">{{ appt.status }}</span>
              </td>
            </tr>
            <tr v-if="appointments.length === 0">
              <td colspan="5" class="px-4 py-6 text-center text-gray-400">Приёмов пока нет.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>
  </div>
</template>
