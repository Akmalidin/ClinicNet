<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { patientsApi, triageApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

// Same reusable-by-branch pattern as ReferralQueueWidget.vue (pass
// `branch` for a branch dashboard, omit for network-wide) and the same
// client-side branch guard for the same reason: never trust that GET
// /triage-suggestions/ already filtered correctly — re-check every row
// against auth.triageBranches (independently fetched via /me/, computed
// server-side by the same rbac.branches_for_permission() the viewset
// itself uses). Unlike referrals there's no "own" bypass here — a triage
// suggestion isn't owned by a doctor, only branch-scoped.
const props = defineProps({
  branch: { type: [String, Number], default: null },
})

const auth = useAuthStore()

const suggestions = ref([])
const loadError = ref('')
const droppedCount = ref(0)

const actionRowId = ref(null) // 'confirm' | 'reject'
const actionKind = ref(null)
const actionError = ref('')
const actionSubmitting = ref(false)
const rejectReason = ref('')

const patientQuery = ref('')
const patientResults = ref([])
const patientSearching = ref(false)
const selectedPatient = ref(null)
let searchTimer = null

function isVisible(suggestion) {
  if (!auth.triageBranches.includes(suggestion.branch)) return false
  if (props.branch != null) {
    return suggestion.branch === Number(props.branch)
  }
  return true
}

async function load() {
  loadError.value = ''
  try {
    const { data } = await triageApi.list(props.branch != null ? { branch: props.branch } : {})
    const rows = data.results ?? data
    const visible = rows.filter(isVisible)
    droppedCount.value = rows.length - visible.length
    if (droppedCount.value > 0) {
      // eslint-disable-next-line no-console
      console.error(
        `TriageQueueWidget: dropped ${droppedCount.value} row(s) that failed the client-side ` +
          'branch guard — the backend returned suggestions outside what /me/ says this user can see.',
      )
    }
    suggestions.value = visible
  } catch {
    loadError.value = 'Не удалось загрузить очередь AI-триажа.'
  }
}
onMounted(load)
watch(() => props.branch, load)

function closeAction() {
  actionRowId.value = null
  actionKind.value = null
  actionError.value = ''
  rejectReason.value = ''
  patientQuery.value = ''
  patientResults.value = []
  selectedPatient.value = null
}

function openAction(suggestion, kind) {
  actionRowId.value = suggestion.id
  actionKind.value = kind
  actionError.value = ''
  rejectReason.value = ''
  patientQuery.value = ''
  patientResults.value = []
  selectedPatient.value = null
  // Convenience, not auto-linking — confirm() still requires an explicit
  // pick below; this only pre-fills the search box with the phone the
  // backend already flagged as matching an existing Patient.
  if (kind === 'confirm' && suggestion.matched_patient_candidate) {
    patientQuery.value = suggestion.contact_phone || ''
  }
}

watch(patientQuery, (value) => {
  clearTimeout(searchTimer)
  if (!value || value.trim().length < 2) {
    patientResults.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    patientSearching.value = true
    try {
      const { data } = await patientsApi.list({ search: value.trim() })
      patientResults.value = data.results ?? data
    } catch {
      patientResults.value = []
    } finally {
      patientSearching.value = false
    }
  }, 300)
})

function pickPatient(patient) {
  selectedPatient.value = patient
  patientResults.value = []
  patientQuery.value = `${patient.first_name} ${patient.last_name}`
}

function pickCandidate(suggestion) {
  const candidate = suggestion.matched_patient_candidate
  if (!candidate) return
  selectedPatient.value = { id: candidate.id, first_name: candidate.name, last_name: '' }
  patientQuery.value = candidate.name
  patientResults.value = []
}

function formatDateTime(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

async function submitConfirm(suggestion) {
  if (!selectedPatient.value) {
    actionError.value = 'Выберите пациента из списка.'
    return
  }
  actionError.value = ''
  actionSubmitting.value = true
  try {
    await triageApi.confirm(suggestion.id, selectedPatient.value.id)
    closeAction()
    await load()
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось подтвердить предложение.'
  } finally {
    actionSubmitting.value = false
  }
}

async function submitReject(suggestion) {
  actionError.value = ''
  actionSubmitting.value = true
  try {
    await triageApi.reject(suggestion.id, rejectReason.value.trim())
    closeAction()
    await load()
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось отклонить предложение.'
  } finally {
    actionSubmitting.value = false
  }
}

const statusBadge = {
  pending: 'badge-yellow',
  confirmed: 'badge-green',
  rejected: 'badge-red',
  expired: 'badge-gray',
}
const statusLabel = {
  pending: 'Ожидает', confirmed: 'Подтверждено', rejected: 'Отклонено', expired: 'Слот истёк',
}

const pendingSuggestions = computed(() => suggestions.value.filter((s) => s.status === 'pending'))
</script>

<template>
  <div class="card">
    <div v-if="loadError" class="p-4 text-sm text-red-600">{{ loadError }}</div>
    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="border-b border-gray-100 text-left text-gray-500">
          <tr>
            <th class="px-4 py-2 font-medium">Контакт</th>
            <th class="px-4 py-2 font-medium">Жалоба</th>
            <th class="px-4 py-2 font-medium">Специальность</th>
            <th class="px-4 py-2 font-medium">Предложенный слот</th>
            <th class="px-4 py-2 font-medium">Статус</th>
            <th class="px-4 py-2 font-medium">Действия</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <template v-for="suggestion in pendingSuggestions" :key="suggestion.id">
            <tr>
              <td class="px-4 py-2">
                {{ suggestion.contact_name || 'Без имени (Telegram)' }}
                <div class="text-xs text-gray-500">{{ suggestion.contact_phone }}</div>
              </td>
              <td class="px-4 py-2 text-gray-500 max-w-xs">{{ suggestion.symptom_text }}</td>
              <td class="px-4 py-2">{{ suggestion.specialty_name }}</td>
              <td class="px-4 py-2">
                {{ suggestion.doctor_name }}<br />
                <span class="text-xs text-gray-500">
                  {{ formatDateTime(suggestion.suggested_starts_at) }} · {{ suggestion.branch_name }}
                </span>
              </td>
              <td class="px-4 py-2">
                <span :class="statusBadge[suggestion.status] ?? 'badge-gray'">
                  {{ statusLabel[suggestion.status] ?? suggestion.status }}
                </span>
              </td>
              <td class="px-4 py-2 whitespace-nowrap">
                <button class="btn-secondary text-xs px-2 py-1 mr-1" @click="openAction(suggestion, 'confirm')">
                  Подтвердить
                </button>
                <button class="btn-secondary text-xs px-2 py-1" @click="openAction(suggestion, 'reject')">
                  Отклонить
                </button>
              </td>
            </tr>

            <tr v-if="actionRowId === suggestion.id" class="bg-gray-50">
              <td colspan="6" class="px-4 py-3">
                <div v-if="actionKind === 'confirm'" class="space-y-2">
                  <p
                    v-if="suggestion.matched_patient_candidate"
                    class="text-xs text-gray-500"
                  >
                    Похоже на существующего пациента:
                    <button class="badge-blue" @click="pickCandidate(suggestion)">
                      {{ suggestion.matched_patient_candidate.name }} — выбрать
                    </button>
                    (это подсказка по телефону, не автоматическая привязка — подтверди выбор явно)
                  </p>
                  <div>
                    <label class="block text-xs font-medium text-gray-500 mb-1">
                      Найти пациента (имя или телефон)
                    </label>
                    <input v-model="patientQuery" class="form-input" placeholder="Иванов или +7900..." />
                  </div>
                  <p v-if="patientSearching" class="text-xs text-gray-400">Ищем…</p>
                  <ul v-else-if="patientResults.length" class="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-40 overflow-y-auto">
                    <li
                      v-for="patient in patientResults"
                      :key="patient.id"
                      class="px-3 py-1.5 text-sm hover:bg-gray-100 cursor-pointer"
                      @click="pickPatient(patient)"
                    >
                      {{ patient.first_name }} {{ patient.last_name }}
                      <span class="text-xs text-gray-500">{{ patient.phone }}</span>
                    </li>
                  </ul>
                  <p v-if="selectedPatient" class="text-xs text-green-700">
                    Выбран: {{ selectedPatient.first_name }} {{ selectedPatient.last_name }}
                  </p>
                  <p v-else-if="patientQuery.trim().length >= 2 && !patientSearching && !patientResults.length" class="text-xs text-gray-400">
                    Совпадений нет — заведите пациента через карточку пациента, затем повторите.
                  </p>
                  <div class="flex gap-2">
                    <button
                      class="btn-primary text-sm"
                      :disabled="actionSubmitting || !selectedPatient"
                      @click="submitConfirm(suggestion)"
                    >
                      Подтвердить запись
                    </button>
                    <button class="btn-secondary text-sm" @click="closeAction">Отмена</button>
                  </div>
                </div>

                <div v-else-if="actionKind === 'reject'" class="flex items-end gap-2">
                  <div class="flex-1">
                    <label class="block text-xs font-medium text-gray-500 mb-1">
                      Причина отказа (необязательно)
                    </label>
                    <input v-model="rejectReason" class="form-input" />
                  </div>
                  <button class="btn-primary text-sm" :disabled="actionSubmitting" @click="submitReject(suggestion)">
                    Отклонить
                  </button>
                  <button class="btn-secondary text-sm" @click="closeAction">Отмена</button>
                </div>

                <p v-if="actionError" class="text-sm text-red-600 mt-2">{{ actionError }}</p>
              </td>
            </tr>
          </template>

          <tr v-if="pendingSuggestions.length === 0">
            <td colspan="6" class="px-4 py-6 text-center text-gray-400">Новых предложений от бота нет.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
