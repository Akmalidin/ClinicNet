<script setup>
import { computed, onMounted, ref } from 'vue'

import { admissionsApi, vitalsApi } from '../api'

const props = defineProps({
  id: { type: [String, Number], required: true }, // admission id
})

const admission = ref(null)
const admissionError = ref('')
const records = ref([])
const recordsError = ref('')

async function loadAdmission() {
  admissionError.value = ''
  try {
    const { data } = await admissionsApi.get(props.id)
    admission.value = data
  } catch {
    admissionError.value = 'Не удалось загрузить госпитализацию.'
  }
}
async function loadRecords() {
  recordsError.value = ''
  try {
    const { data } = await vitalsApi.list(props.id)
    records.value = data.results ?? data
  } catch {
    recordsError.value = 'Не удалось загрузить лист наблюдения.'
  }
}
onMounted(() => {
  loadAdmission()
  loadRecords()
})

// Хронологически, старые сверху — API отдаёт -recorded_at (модель
// append-only, см. VitalsRecord's докстринг), в макете лист читается
// сверху вниз от раннего замера к позднему.
const chronological = computed(() => [...records.value].reverse())

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

// Простые статические пороги для подсветки — не диагноз, только "на что
// медсестре стоит обратить внимание", тот же дух, что apps.churn's
// "простая формула, не ML". Ничего из этого не хранится бэкендом —
// чистое отображение.
function isBpWarn(r) {
  return (r.blood_pressure_systolic != null && r.blood_pressure_systolic > 140)
    || (r.blood_pressure_diastolic != null && r.blood_pressure_diastolic > 90)
}
function isPulseWarn(r) {
  return r.pulse != null && (r.pulse > 100 || r.pulse < 50)
}
function isTempWarn(r) {
  return r.temperature != null && (Number(r.temperature) >= 37.5 || Number(r.temperature) < 36)
}
function isSpo2Warn(r) {
  return r.spo2 != null && r.spo2 < 95
}

const formOpen = ref(false)
const systolic = ref('')
const diastolic = ref('')
const pulse = ref('')
const temperature = ref('')
const spo2 = ref('')
const note = ref('')
const submitting = ref(false)
const submitError = ref('')

function resetForm() {
  systolic.value = ''
  diastolic.value = ''
  pulse.value = ''
  temperature.value = ''
  spo2.value = ''
  note.value = ''
  submitError.value = ''
}
function openForm() {
  resetForm()
  formOpen.value = true
}

async function submit() {
  submitError.value = ''
  submitting.value = true
  try {
    await vitalsApi.create({
      admission: props.id,
      blood_pressure_systolic: systolic.value || null,
      blood_pressure_diastolic: diastolic.value || null,
      pulse: pulse.value || null,
      temperature: temperature.value || null,
      spo2: spo2.value || null,
      note: note.value,
    })
    formOpen.value = false
    await loadRecords()
  } catch (e) {
    const data = e.response?.data
    submitError.value =
      (data && (data.detail || Object.values(data).flat().join(' '))) || 'Не удалось сохранить замер.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Лист наблюдения{{ admission ? ' — ' + admission.patient_name : '' }}</h1>
        <div class="meta" v-if="admission">Койка {{ admission.room_name }}-{{ admission.bed_label }} · {{ admission.department_name }}</div>
      </div>
      <button class="btn-add" @click="openForm">+ Внести замер</button>
    </div>

    <p v-if="admissionError" style="padding:16px 32px;font-size:13px;color:var(--red)">{{ admissionError }}</p>

    <div class="content">
      <div v-if="formOpen" class="panel" style="margin-bottom:16px;padding:20px">
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px">
          <div class="field">
            <div class="field-label">АД сист.</div>
            <input v-model="systolic" type="number" class="select-field" placeholder="120" />
          </div>
          <div class="field">
            <div class="field-label">АД диаст.</div>
            <input v-model="diastolic" type="number" class="select-field" placeholder="80" />
          </div>
          <div class="field">
            <div class="field-label">Пульс</div>
            <input v-model="pulse" type="number" class="select-field" placeholder="76" />
          </div>
          <div class="field">
            <div class="field-label">Темп.</div>
            <input v-model="temperature" type="number" step="0.1" class="select-field" placeholder="36.6" />
          </div>
          <div class="field">
            <div class="field-label">SpO₂, %</div>
            <input v-model="spo2" type="number" class="select-field" placeholder="98" />
          </div>
        </div>
        <div class="field" style="margin-top:10px">
          <div class="field-label">Заметка (необязательно)</div>
          <input v-model="note" class="select-field" />
        </div>
        <p v-if="submitError" style="font-size:12.5px;color:var(--red);margin-top:8px">{{ submitError }}</p>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="btn btn-mint" :disabled="submitting" @click="submit">{{ submitting ? 'Сохраняем…' : 'Сохранить замер' }}</button>
          <button class="btn btn-outline" @click="formOpen = false">Отмена</button>
        </div>
      </div>

      <p v-if="recordsError" style="font-size:13px;color:var(--red)">{{ recordsError }}</p>

      <div v-else class="panel" style="overflow:hidden">
        <div style="overflow-x:auto">
          <table class="vitals-table">
            <thead>
              <tr>
                <th>Время</th><th>Давление</th><th>Пульс</th><th>Темп.</th><th>SpO₂</th><th>Зафиксировал</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in chronological" :key="r.id">
                <td class="mono">{{ formatTime(r.recorded_at) }}</td>
                <td class="val" :class="{ warn: isBpWarn(r) }">
                  {{ r.blood_pressure_systolic != null && r.blood_pressure_diastolic != null
                    ? `${r.blood_pressure_systolic}/${r.blood_pressure_diastolic}` : '—' }}
                </td>
                <td class="val" :class="{ warn: isPulseWarn(r) }">{{ r.pulse ?? '—' }}</td>
                <td class="val" :class="{ warn: isTempWarn(r) }">{{ r.temperature ?? '—' }}</td>
                <td class="val" :class="{ warn: isSpo2Warn(r) }">{{ r.spo2 != null ? r.spo2 + '%' : '—' }}</td>
                <td class="by">{{ r.recorded_by_name }}</td>
              </tr>
              <tr v-if="chronological.length === 0">
                <td colspan="6" style="text-align:center;color:var(--ink-soft);padding:24px">Замеров пока нет.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
