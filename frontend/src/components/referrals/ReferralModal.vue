<script setup>
import { computed, ref, watch } from 'vue'

import { branchesApi, doctorsApi, referralsApi, specialtiesApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

// Two scenarios (ClinicNet-Referrals-Prompt.md section 6/7, steps 5-6):
// 'same_branch' — врач в филиале текущего осмотра, слот подбирается сразу.
// 'cross_branch' — специальность -> филиал -> (опционально) конкретный врач;
// без выбора врача направление уходит "на специальность" (to_specialty),
// её потом разбирает координатор/принимающий филиал.
const props = defineProps({
  open: { type: Boolean, required: true },
  patient: { type: Object, required: true },
  // The visit this referral is created from — supplies from_branch (always
  // the visit's branch), source_visit, and the reason/clinical_note prefill.
  visit: { type: Object, required: true },
})
const emit = defineEmits(['close', 'created'])

const auth = useAuthStore()

const mode = ref('same_branch') // 'same_branch' | 'cross_branch'

const specialties = ref([])
const branches = ref([])
const pickersError = ref('')

const selectedSpecialtyId = ref(null) // cross_branch only
const selectedBranchId = ref(null) // cross_branch only — becomes to_branch

const doctors = ref([])
const doctorsError = ref('')
const doctorsLoading = ref(false)
const selectedDoctorId = ref(null) // required in same_branch, optional in cross_branch

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

// The branch a cross-branch referral can go to — never the visit's own
// branch, that's what the "same_branch" tab is for.
const crossBranchOptions = computed(() => branches.value.filter((b) => b.id !== props.visit.branch))

function reset() {
  mode.value = 'same_branch'
  selectedSpecialtyId.value = null
  selectedBranchId.value = null
  selectedDoctorId.value = null
  doctors.value = []
  slotsByDate.value = {}
  reason.value = props.visit?.reason ?? ''
  clinicalNote.value = props.visit?.clinical_note ?? ''
  priority.value = 'routine'
  submitError.value = ''
}

async function loadDoctorsForSameBranch() {
  doctorsError.value = ''
  doctorsLoading.value = true
  try {
    const { data } = await doctorsApi.list({ branch: props.visit.branch })
    doctors.value = data.filter((d) => d.id !== auth.user?.id) // can't refer to yourself
  } catch {
    doctorsError.value = 'Не удалось загрузить список врачей филиала.'
  } finally {
    doctorsLoading.value = false
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    reset()
    pickersError.value = ''
    loadDoctorsForSameBranch()
    try {
      const [specialtiesRes, branchesRes] = await Promise.all([
        specialtiesApi.list(),
        branchesApi.directory(),
      ])
      specialties.value = specialtiesRes.data
      branches.value = branchesRes.data
    } catch {
      pickersError.value = 'Не удалось загрузить справочники специальностей/филиалов.'
    }
  },
  { immediate: true },
)

watch(mode, (newMode) => {
  selectedDoctorId.value = null
  slotsByDate.value = {}
  if (newMode === 'same_branch') {
    selectedSpecialtyId.value = null
    selectedBranchId.value = null
    loadDoctorsForSameBranch()
  } else {
    doctors.value = []
  }
})

// Cross-branch doctor list: needs specialty + branch both picked, per the
// spec's own order (специальность -> филиал -> врач).
watch([selectedSpecialtyId, selectedBranchId], async ([specialtyId, branchId]) => {
  if (mode.value !== 'cross_branch') return
  selectedDoctorId.value = null
  doctors.value = []
  if (!specialtyId || !branchId) return
  doctorsError.value = ''
  doctorsLoading.value = true
  try {
    const specialty = specialties.value.find((s) => s.id === specialtyId)
    const { data } = await doctorsApi.list({ branch: branchId, specialty: specialty?.code })
    doctors.value = data.filter((d) => d.id !== auth.user?.id)
  } catch {
    doctorsError.value = 'Не удалось загрузить список врачей.'
  } finally {
    doctorsLoading.value = false
  }
})

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
const canSubmit = computed(() => {
  if (submitting.value || !reason.value.trim()) return false
  if (mode.value === 'same_branch') return !!selectedDoctorId.value
  // cross_branch: specialty + branch required, doctor optional (falls back
  // to to_specialty — "к любому врачу этой специальности в этом филиале").
  return !!selectedSpecialtyId.value && !!selectedBranchId.value
})

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

async function submit() {
  submitError.value = ''
  submitting.value = true
  try {
    const crossBranch = mode.value === 'cross_branch'
    const { data } = await referralsApi.create({
      patient: props.patient.id,
      to_doctor: selectedDoctorId.value || null,
      to_specialty: crossBranch && !selectedDoctorId.value ? selectedSpecialtyId.value : null,
      from_branch: props.visit.branch,
      to_branch: crossBranch ? selectedBranchId.value : props.visit.branch,
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

      <div class="flex rounded-lg border border-gray-200 p-1 text-sm">
        <button
          class="flex-1 rounded-md py-1.5 font-medium transition-colors"
          :class="mode === 'same_branch' ? 'bg-primary text-white' : 'text-gray-600 hover:bg-gray-50'"
          @click="mode = 'same_branch'"
        >
          Внутри филиала
        </button>
        <button
          class="flex-1 rounded-md py-1.5 font-medium transition-colors"
          :class="mode === 'cross_branch' ? 'bg-primary text-white' : 'text-gray-600 hover:bg-gray-50'"
          @click="mode = 'cross_branch'"
        >
          В другой филиал
        </button>
      </div>

      <p v-if="pickersError" class="text-sm text-red-600">{{ pickersError }}</p>

      <template v-if="mode === 'same_branch'">
        <p class="text-sm text-gray-500">Внутри филиала «{{ visit.branch_name }}».</p>

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
          <p v-if="doctors.length === 0 && !doctorsError && !doctorsLoading" class="text-xs text-gray-400 mt-1">
            В этом филиале нет других врачей для направления.
          </p>
        </div>
      </template>

      <template v-else>
        <p class="text-sm text-gray-500">
          Из «{{ visit.branch_name }}» в другой филиал сети — сначала специальность, затем филиал и,
          при желании, конкретный врач.
        </p>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Специальность</label>
          <select v-model="selectedSpecialtyId" class="form-input">
            <option :value="null" disabled>Выберите специальность…</option>
            <option v-for="specialty in specialties" :key="specialty.id" :value="specialty.id">
              {{ specialty.name }}
            </option>
          </select>
        </div>

        <div v-if="selectedSpecialtyId">
          <label class="block text-sm font-medium text-gray-700 mb-1">Филиал</label>
          <select v-model="selectedBranchId" class="form-input">
            <option :value="null" disabled>Выберите филиал…</option>
            <option v-for="branch in crossBranchOptions" :key="branch.id" :value="branch.id">
              {{ branch.name }}
            </option>
          </select>
        </div>

        <div v-if="selectedSpecialtyId && selectedBranchId">
          <label class="block text-sm font-medium text-gray-700 mb-1">
            Врач <span class="text-gray-400 font-normal">(необязательно)</span>
          </label>
          <p v-if="doctorsError" class="text-sm text-red-600">{{ doctorsError }}</p>
          <select v-else v-model="selectedDoctorId" class="form-input">
            <option :value="null">На специальность — без конкретного врача</option>
            <option v-for="doctor in doctors" :key="doctor.id" :value="doctor.id">
              {{ doctor.display_name }}
            </option>
          </select>
          <p v-if="doctors.length === 0 && !doctorsError && !doctorsLoading" class="text-xs text-gray-400 mt-1">
            В этом филиале нет врачей с этой специальностью — направление всё равно можно создать
            «на специальность», его разберёт координатор филиала.
          </p>
        </div>
      </template>

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
