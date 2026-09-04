<script setup>
import { computed, ref, watch } from 'vue'

import { appointmentsApi, branchesApi, doctorsApi, referralsApi, specialtiesApi } from '../../api'
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
// Picking a slot here is optional — the mockup's primary flow ("Направить
// на 15:00") books it immediately, same two-call sequence
// ReferralQueueWidget.vue's bookSlot() already uses (create Appointment,
// then referrals/{id}/schedule/ to link it) — reused here rather than
// reinvented. Leaving no slot selected keeps the older "pending, book
// later" flow working exactly as before.
const selectedSlot = ref(null)

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
  selectedSlot.value = null
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
  selectedSlot.value = null
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

function selectSlot(slot) {
  selectedSlot.value = selectedSlot.value?.starts_at === slot.starts_at ? null : slot
}

async function submit() {
  submitError.value = ''
  submitting.value = true
  try {
    const crossBranch = mode.value === 'cross_branch'
    const toBranch = crossBranch ? selectedBranchId.value : props.visit.branch
    const { data } = await referralsApi.create({
      patient: props.patient.id,
      to_doctor: selectedDoctorId.value || null,
      to_specialty: crossBranch && !selectedDoctorId.value ? selectedSpecialtyId.value : null,
      from_branch: props.visit.branch,
      to_branch: toBranch,
      source_visit: props.visit.id,
      reason: reason.value.trim(),
      clinical_note: clinicalNote.value,
      priority: priority.value,
      // diagnosis_snapshot is deliberately not sent — the backend derives
      // it from source_visit itself (apps/referrals/views.py perform_create),
      // read-only on the serializer, so it can't be forged from here either.
    })

    let result = data
    if (selectedSlot.value && selectedDoctorId.value) {
      // Book it immediately, same sequence ReferralQueueWidget.vue's
      // bookSlot() uses — Appointment.clean()'s own overlap-check still
      // re-validates the slot wasn't taken in the meantime.
      const { data: appointment } = await appointmentsApi.create({
        branch: toBranch,
        patient: props.patient.id,
        doctor: selectedDoctorId.value,
        starts_at: selectedSlot.value.starts_at,
        ends_at: selectedSlot.value.ends_at,
      })
      const { data: scheduled } = await referralsApi.schedule(data.id, appointment.id)
      result = scheduled
    }

    emit('created', result)
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

const submitLabel = computed(() => {
  if (submitting.value) return 'Создаём…'
  if (selectedSlot.value) return `Направить на ${formatTime(selectedSlot.value.starts_at)}`
  return 'Создать направление'
})
</script>

<template>
  <div v-if="open" class="mockup-page mockup-modal-overlay" @click.self="emit('close')">
    <div class="mockup-modal">
      <div class="modal-head">
        <h3>Направить пациента</h3>
        <button class="close-x" @click="emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <div class="patient-strip">
          <div class="avatar">{{ (patient.first_name?.[0] ?? '') + (patient.last_name?.[0] ?? '') }}</div>
          <div style="font-size:13px;font-weight:600;color:var(--mint-d)">{{ patient.first_name }} {{ patient.last_name }}</div>
        </div>

        <div>
          <div class="field-label">Куда направляем</div>
          <div class="scope-toggle">
            <div class="scope-btn" :class="{ active: mode === 'same_branch' }" @click="mode = 'same_branch'">
              Этот филиал
            </div>
            <div class="scope-btn" :class="{ active: mode === 'cross_branch' }" @click="mode = 'cross_branch'">
              Другой филиал сети
            </div>
          </div>
        </div>

        <p v-if="pickersError" style="font-size:13px;color:var(--red)">{{ pickersError }}</p>

        <template v-if="mode === 'same_branch'">
          <div>
            <div class="field-label">Врач — «{{ visit.branch_name }}»</div>
            <p v-if="doctorsError" style="font-size:13px;color:var(--red)">{{ doctorsError }}</p>
            <select v-else v-model="selectedDoctorId" class="select-field">
              <option :value="null" disabled>Выберите врача…</option>
              <option v-for="doctor in doctors" :key="doctor.id" :value="doctor.id">
                {{ doctor.display_name }}
                <template v-if="doctor.specialties.length">
                  ({{ doctor.specialties.map((s) => s.name).join(', ') }})
                </template>
              </option>
            </select>
            <p v-if="doctors.length === 0 && !doctorsError && !doctorsLoading" style="font-size:11px;color:var(--ink-soft);margin-top:4px">
              В этом филиале нет других врачей для направления.
            </p>
          </div>
        </template>

        <template v-else>
          <div>
            <div class="field-label">Специальность</div>
            <select v-model="selectedSpecialtyId" class="select-field">
              <option :value="null" disabled>Выберите специальность…</option>
              <option v-for="specialty in specialties" :key="specialty.id" :value="specialty.id">
                {{ specialty.name }}
              </option>
            </select>
          </div>

          <div v-if="selectedSpecialtyId">
            <div class="field-label">Филиал</div>
            <select v-model="selectedBranchId" class="select-field">
              <option :value="null" disabled>Выберите филиал…</option>
              <option v-for="branch in crossBranchOptions" :key="branch.id" :value="branch.id">
                {{ branch.name }}
              </option>
            </select>
          </div>

          <div v-if="selectedSpecialtyId && selectedBranchId">
            <div class="field-label">Врач (необязательно)</div>
            <p v-if="doctorsError" style="font-size:13px;color:var(--red)">{{ doctorsError }}</p>
            <select v-else v-model="selectedDoctorId" class="select-field">
              <option :value="null">На специальность — без конкретного врача</option>
              <option v-for="doctor in doctors" :key="doctor.id" :value="doctor.id">
                {{ doctor.display_name }}
              </option>
            </select>
            <p v-if="doctors.length === 0 && !doctorsError && !doctorsLoading" style="font-size:11px;color:var(--ink-soft);margin-top:4px">
              В этом филиале нет врачей с этой специальностью — направление всё равно можно создать
              «на специальность», его разберёт координатор филиала.
            </p>
          </div>
        </template>

        <div v-if="selectedDoctorId">
          <div class="field-label">Свободные слоты — {{ selectedDoctor?.display_name }}</div>
          <p v-if="slotsLoading" style="font-size:12.5px;color:var(--ink-soft)">Загружаем слоты…</p>
          <p v-else-if="!hasAnySlot" style="font-size:12.5px;color:var(--ink-soft)">
            Свободных окон не найдено — направление всё равно можно создать, слот подтвердит
            принимающий врач или координатор.
          </p>
          <template v-else>
            <div v-for="date in dates" :key="date" style="margin-bottom:6px">
              <p v-if="slotsByDate[date]?.length" style="font-size:11px;color:var(--ink-soft);margin-bottom:4px">{{ date }}</p>
              <div class="slots-grid">
                <div
                  v-for="slot in slotsByDate[date] ?? []"
                  :key="slot.starts_at"
                  class="slot-btn"
                  :class="{ selected: selectedSlot?.starts_at === slot.starts_at }"
                  @click="selectSlot(slot)"
                >
                  {{ formatTime(slot.starts_at) }}
                </div>
              </div>
            </div>
          </template>
        </div>

        <div>
          <div class="field-label">Причина направления</div>
          <textarea v-model="reason" required maxlength="255"></textarea>
        </div>

        <div>
          <div class="field-label">Клиническая заметка</div>
          <textarea v-model="clinicalNote"></textarea>
        </div>

        <div>
          <div class="field-label">Приоритет</div>
          <div class="priority-row">
            <div class="prio-chip" :class="{ active: priority === 'routine' }" @click="priority = 'routine'">Плановое</div>
            <div class="prio-chip urgent" :class="{ active: priority === 'urgent' }" @click="priority = 'urgent'">Срочное</div>
            <div class="prio-chip emergency" :class="{ active: priority === 'emergency' }" @click="priority = 'emergency'">Экстренное</div>
          </div>
        </div>

        <p v-if="submitError" style="font-size:13px;color:var(--red)">{{ submitError }}</p>
      </div>

      <div class="modal-foot">
        <button class="btn btn-ghost" :disabled="submitting" @click="emit('close')">Отмена</button>
        <button class="btn btn-mint" :disabled="!canSubmit" @click="submit">{{ submitLabel }}</button>
      </div>
    </div>
  </div>
</template>
