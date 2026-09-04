<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { admissionsApi, doctorsApi, patientsApi } from '../api'
import { useAuthStore } from '../stores/auth'

const props = defineProps({
  id: { type: [String, Number], required: true },
})

const auth = useAuthStore()

const patient = ref(null)
const patientError = ref('')

const departments = ref([])
const optionsError = ref('')
const optionsLoading = ref(true)

const selectedDepartmentId = ref(null)
const selectedBedId = ref(null)

const doctors = ref([])
const doctorsError = ref('')
const doctorsLoading = ref(false)
const selectedDoctorId = ref(null)

const diagnosis = ref('')
const reason = ref('planned')
const notes = ref('')

const submitting = ref(false)
const submitError = ref('')
const created = ref(null)

const REASON_LABELS = {
  planned: 'Плановая операция',
  emergency: 'Экстренная госпитализация',
  transfer: 'Перевод из другого отделения',
}
const BED_STATUS_LABELS = {
  free: 'свободна', occupied: 'занята', cleaning: 'уборка', reserved: 'резерв',
}

async function loadPatient() {
  patientError.value = ''
  try {
    const { data } = await patientsApi.get(props.id)
    patient.value = data
  } catch {
    patientError.value = 'Не удалось загрузить пациента.'
  }
}

async function loadOptions() {
  optionsError.value = ''
  optionsLoading.value = true
  try {
    const { data } = await admissionsApi.intakeOptions()
    departments.value = data
  } catch (e) {
    optionsError.value =
      e.response?.status === 403
        ? 'Недостаточно прав для госпитализации — нет ни одного отделения, куда можно принять пациента.'
        : 'Не удалось загрузить список отделений и коек.'
  } finally {
    optionsLoading.value = false
  }
}

onMounted(() => {
  loadPatient()
  loadOptions()
})

const selectedDepartment = computed(() => departments.value.find((d) => d.id === selectedDepartmentId.value))
const selectedBed = computed(() => {
  if (!selectedDepartment.value) return null
  for (const room of selectedDepartment.value.rooms) {
    const bed = room.beds.find((b) => b.id === selectedBedId.value)
    if (bed) return { ...bed, roomName: room.name }
  }
  return null
})

watch(selectedDepartmentId, async (departmentId) => {
  selectedBedId.value = null
  doctors.value = []
  selectedDoctorId.value = null
  const department = departments.value.find((d) => d.id === departmentId)
  if (!department) return
  doctorsLoading.value = true
  doctorsError.value = ''
  try {
    const { data } = await doctorsApi.list({ branch: department.branch })
    doctors.value = data
  } catch {
    doctorsError.value = 'Не удалось загрузить список врачей филиала.'
  } finally {
    doctorsLoading.value = false
  }
})

function pickBed(bed) {
  if (bed.status !== 'free' && bed.status !== 'reserved') return
  selectedBedId.value = selectedBedId.value === bed.id ? null : bed.id
}

const canSubmit = computed(
  () => !submitting.value && selectedDepartmentId.value && selectedBedId.value
    && selectedDoctorId.value && diagnosis.value.trim(),
)

async function submit() {
  if (!canSubmit.value) return
  submitError.value = ''
  submitting.value = true
  try {
    const { data } = await admissionsApi.create({
      patient: props.id,
      department: selectedDepartmentId.value,
      bed: selectedBedId.value,
      attending_doctor: selectedDoctorId.value,
      diagnosis_at_admission: diagnosis.value.trim(),
      reason: reason.value,
      notes: notes.value,
    })
    created.value = data
  } catch (e) {
    const data = e.response?.data
    submitError.value =
      (data && (data.detail || Object.values(data).flat().join(' '))) || 'Не удалось госпитализировать пациента.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Госпитализация{{ patient ? ' — ' + patient.first_name + ' ' + patient.last_name : '' }}</h1>
        <div class="meta" v-if="selectedDepartment">{{ selectedDepartment.name }} · {{ selectedDepartment.branch_name }}</div>
      </div>
    </div>

    <div class="content" style="max-width:640px;margin:0 auto">
      <p v-if="patientError" style="font-size:13px;color:var(--red)">{{ patientError }}</p>

      <div v-if="created" class="panel" style="text-align:center;padding:32px">
        <h3 style="color:var(--mint-d);margin-bottom:8px">Пациент госпитализирован</h3>
        <p style="font-size:13px;color:var(--ink-soft)">
          {{ selectedDepartment?.name }}, койка {{ selectedBed?.roomName }}-{{ selectedBed?.label }}
        </p>
        <RouterLink :to="{ name: 'patient-card', params: { id: props.id } }" class="btn btn-mint" style="display:inline-block;margin-top:16px;text-decoration:none">
          К карте пациента
        </RouterLink>
      </div>

      <template v-else>
        <div class="panel">
          <h3>Данные поступления</h3>
          <div class="field">
            <div class="field-label">Диагноз при поступлении</div>
            <input v-model="diagnosis" class="select-field" placeholder="Например: K01.1 Ретинированный зуб" />
          </div>
          <div class="field">
            <div class="field-label">Основание</div>
            <select v-model="reason" class="select-field">
              <option v-for="(label, value) in REASON_LABELS" :key="value" :value="value">{{ label }}</option>
            </select>
          </div>
          <div class="field" v-if="selectedDepartment">
            <div class="field-label">Лечащий врач — «{{ selectedDepartment.branch_name }}»</div>
            <p v-if="doctorsError" style="font-size:12.5px;color:var(--red)">{{ doctorsError }}</p>
            <select v-else v-model="selectedDoctorId" class="select-field">
              <option :value="null" disabled>{{ doctorsLoading ? 'Загружаем…' : 'Выберите врача…' }}</option>
              <option v-for="doctor in doctors" :key="doctor.id" :value="doctor.id">{{ doctor.display_name }}</option>
            </select>
          </div>
        </div>

        <div class="panel">
          <h3>Отделение и койка</h3>
          <p v-if="optionsLoading" style="font-size:12.5px;color:var(--ink-soft)">Загружаем отделения…</p>
          <p v-else-if="optionsError" style="font-size:12.5px;color:var(--red)">{{ optionsError }}</p>
          <template v-else>
            <div class="field">
              <div class="field-label">Отделение</div>
              <select v-model="selectedDepartmentId" class="select-field">
                <option :value="null" disabled>Выберите отделение…</option>
                <option v-for="department in departments" :key="department.id" :value="department.id">
                  {{ department.name }} — {{ department.branch_name }}
                </option>
              </select>
              <p v-if="departments.length === 0" style="font-size:11px;color:var(--ink-soft);margin-top:4px">
                Нет ни одного отделения, куда можно госпитализировать пациента.
              </p>
            </div>

            <template v-if="selectedDepartment">
              <div class="field" v-for="room in selectedDepartment.rooms" :key="room.id">
                <div class="field-label">Свободные койки — Палата {{ room.name }}</div>
                <p v-if="room.beds.length === 0" style="font-size:11.5px;color:var(--ink-soft)">В палате нет коек.</p>
                <div v-else class="bed-picker">
                  <div
                    v-for="bed in room.beds"
                    :key="bed.id"
                    class="bed-opt mono"
                    :class="{ selected: selectedBedId === bed.id, taken: bed.status !== 'free' && bed.status !== 'reserved' }"
                    @click="pickBed(bed)"
                  >
                    {{ room.name }}-{{ bed.label }}<br />{{ BED_STATUS_LABELS[bed.status] ?? bed.status }}
                  </div>
                </div>
              </div>
            </template>
          </template>
        </div>

        <div class="panel">
          <h3>Заметки</h3>
          <textarea v-model="notes" placeholder="Аллергии, план на ближайшую операцию и т.п."></textarea>
        </div>

        <p v-if="submitError" style="font-size:13px;color:var(--red)">{{ submitError }}</p>

        <button class="btn btn-submit" :disabled="!canSubmit" @click="submit">
          {{ submitting ? 'Госпитализируем…' : selectedBed ? `Госпитализировать в ${selectedBed.roomName}-${selectedBed.label}` : 'Госпитализировать' }}
        </button>
      </template>
    </div>
  </div>
</template>
