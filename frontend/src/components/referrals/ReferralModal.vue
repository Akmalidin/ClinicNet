<script setup>
import { computed, ref, watch } from 'vue'

import { doctorsApi, referralsApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

// Same-branch scenario only (ClinicNet-Referrals-Prompt.md section 6/7,
// step 5) — "специальность -> филиал -> врач" cross-branch picker is step
// 6, a deliberately separate follow-up slice.
const props = defineProps({
  open: { type: Boolean, required: true },
  patient: { type: Object, required: true },
  // The visit this referral is created from — supplies from_branch/to_branch
  // (same branch here), source_visit, and the reason/clinical_note prefill.
  visit: { type: Object, required: true },
})
const emit = defineEmits(['close', 'created'])

const auth = useAuthStore()

const doctors = ref([])
const doctorsError = ref('')
const selectedDoctorId = ref(null)

const slotsByDate = ref({}) // { 'YYYY-MM-DD': [slot, ...] }
const slotsLoading = ref(false)

const reason = ref('')
const clinicalNote = ref('')
const priority = ref('routine')

const submitting = ref(false)
const submitError = ref('')

function nextThreeDates() {
  const dates = []
  const today = new Date()
  for (let i = 0; i < 3; i += 1) {
    const d = new Date(today)
    d.setDate(d.getDate() + i)
    dates.push(d.toISOString().slice(0, 10))
  }
  return dates
}
const dates = nextThreeDates()

function reset() {
  selectedDoctorId.value = null
  slotsByDate.value = {}
  reason.value = props.visit?.reason ?? ''
  clinicalNote.value = props.visit?.clinical_note ?? ''
  priority.value = 'routine'
  submitError.value = ''
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    reset()
    doctorsError.value = ''
    try {
      const { data } = await doctorsApi.list({ branch: props.visit.branch })
      // A doctor can't refer to themselves.
      doctors.value = data.filter((d) => d.id !== auth.user?.id)
    } catch {
      doctorsError.value = 'Не удалось загрузить список врачей филиала.'
    }
  },
  { immediate: true },
)

watch(selectedDoctorId, async (doctorId) => {
  slotsByDate.value = {}
  if (!doctorId) return
  slotsLoading.value = true
  try {
    const results = await Promise.all(dates.map((date) => referralsApi.availableSlots(doctorId, date)))
    const byDate = {}
    dates.forEach((date, i) => {
      byDate[date] = results[i].data
    })
    slotsByDate.value = byDate
  } finally {
    slotsLoading.value = false
  }
})

const selectedDoctor = computed(() => doctors.value.find((d) => d.id === selectedDoctorId.value))
const hasAnySlot = computed(() => Object.values(slotsByDate.value).some((slots) => slots.length > 0))
const canSubmit = computed(() => selectedDoctorId.value && reason.value.trim() && !submitting.value)

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

async function submit() {
  submitError.value = ''
  submitting.value = true
  try {
    const { data } = await referralsApi.create({
      patient: props.patient.id,
      to_doctor: selectedDoctorId.value,
      from_branch: props.visit.branch,
      to_branch: props.visit.branch, // same-branch scenario
      source_visit: props.visit.id,
      reason: reason.value.trim(),
      clinical_note: clinicalNote.value,
      priority: priority.value,
      // diagnosis_snapshot is deliberately not sent — the backend derives
      // it from source_visit itself (apps/referrals/views.py perform_create),
      // read-only on the serializer, so it can't be forged from here either.
    })
    emit('created', data)
    emit('close')
  } catch (e) {
    const data = e.response?.data
    submitError.value =
      (data && (data.detail || Object.values(data).flat().join(' '))) ||
      'Не удалось создать направление.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 bg-black/30 flex items-center justify-center z-40 p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 space-y-4">
      <header class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-gray-900">
          Направить · {{ patient.first_name }} {{ patient.last_name }}
        </h2>
        <button class="text-gray-400 hover:text-gray-600" @click="emit('close')">✕</button>
      </header>

      <p class="text-sm text-gray-500">
        Внутри филиала «{{ visit.branch_name }}». Направление на другой филиал — отдельный шаг,
        появится следующим.
      </p>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Врач</label>
        <p v-if="doctorsError" class="text-sm text-red-600">{{ doctorsError }}</p>
        <select v-else v-model="selectedDoctorId" class="form-input">
          <option :value="null" disabled>Выберите врача…</option>
          <option v-for="doctor in doctors" :key="doctor.id" :value="doctor.id">
            {{ doctor.display_name }}
            <template v-if="doctor.specialties.length">
              ({{ doctor.specialties.map((s) => s.name).join(', ') }})
            </template>
          </option>
        </select>
        <p v-if="doctors.length === 0 && !doctorsError" class="text-xs text-gray-400 mt-1">
          В этом филиале нет других врачей для направления.
        </p>
      </div>

      <div v-if="selectedDoctorId">
        <p class="text-sm font-medium text-gray-700 mb-1">
          Свободные окна {{ selectedDoctor?.display_name }} на ближайшие 3 дня
        </p>
        <p v-if="slotsLoading" class="text-sm text-gray-400">Загружаем слоты…</p>
        <p v-else-if="!hasAnySlot" class="text-sm text-gray-400">
          Свободных окон не найдено — направление всё равно можно создать, слот подтвердит
          принимающий врач или координатор.
        </p>
        <div v-else class="space-y-2">
          <div v-for="date in dates" :key="date">
            <p v-if="slotsByDate[date]?.length" class="text-xs text-gray-500 mb-1">{{ date }}</p>
            <div class="flex flex-wrap gap-1">
              <span v-for="slot in slotsByDate[date] ?? []" :key="slot.starts_at" class="badge-gray">
                {{ formatTime(slot.starts_at) }}–{{ formatTime(slot.ends_at) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Причина направления</label>
        <input v-model="reason" class="form-input" required maxlength="255" />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Клиническая заметка</label>
        <textarea v-model="clinicalNote" class="form-input" rows="3" />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Приоритет</label>
        <select v-model="priority" class="form-input">
          <option value="routine">Плановое</option>
          <option value="urgent">Срочное</option>
          <option value="emergency">Экстренное</option>
        </select>
      </div>

      <p v-if="submitError" class="text-sm text-red-600">{{ submitError }}</p>

      <div class="flex justify-end gap-2 pt-2">
        <button class="btn-secondary" :disabled="submitting" @click="emit('close')">Отмена</button>
        <button class="btn-primary" :disabled="!canSubmit" @click="submit">
          {{ submitting ? 'Создаём…' : 'Создать направление' }}
        </button>
      </div>
    </div>
  </div>
</template>
