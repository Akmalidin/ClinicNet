<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { doctorsApi, patientsApi, referralsApi, triageApi } from '../api'
import { useAuthStore } from '../stores/auth'

// Network-wide (no `branch` prop, unlike TriageQueueWidget which a branch
// dashboard could scope) — same client-side branch guard as everywhere
// else RBAC-filtered rows are rendered: never trust that GET
// /triage-suggestions/ already filtered correctly.
const auth = useAuthStore()

const suggestions = ref([])
const loadError = ref('')
const droppedCount = ref(0)

function isVisible(suggestion) {
  return auth.triageBranches.includes(suggestion.branch)
}

async function load() {
  loadError.value = ''
  try {
    const { data } = await triageApi.list()
    const rows = data.results ?? data
    const visible = rows.filter(isVisible)
    droppedCount.value = rows.length - visible.length
    if (droppedCount.value > 0) {
      // eslint-disable-next-line no-console
      console.error(
        `TriageQueuePage: dropped ${droppedCount.value} row(s) that failed the client-side ` +
          'branch guard — the backend returned suggestions outside what /me/ says this user can see.',
      )
    }
    suggestions.value = visible
  } catch {
    loadError.value = 'Не удалось загрузить очередь AI-триажа.'
  }
}
onMounted(load)

// Тик раз в минуту — только чтобы "X мин назад"/статистика "ожидают > 30
// мин" не застывали до следующего load(), сама очередь по таймеру не
// перезапрашивается (это увеличило бы нагрузку без реальной пользы —
// координатор и так обновит после действия).
const now = ref(Date.now())
let clock = null
onMounted(() => {
  clock = setInterval(() => {
    now.value = Date.now()
  }, 30_000)
})
onUnmounted(() => clearInterval(clock))

function isToday(iso) {
  const d = new Date(iso)
  const today = new Date()
  return d.toDateString() === today.toDateString()
}

const pendingSuggestions = computed(() =>
  suggestions.value
    .filter((s) => s.status === 'pending')
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at)),
)
const historySuggestions = computed(() =>
  suggestions.value
    .filter((s) => ['confirmed', 'rejected', 'expired'].includes(s.status))
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
    .slice(0, 10),
)

// "увер. 61%" — тот же простой эвристический confidence, что и в
// triage_service.classifier (не претензия на клиническую точность,
// см. его докстринг); < 70% помечаем как требующее уточнения.
const CONFIDENCE_UNCERTAIN_BELOW = 70
function isUncertain(suggestion) {
  return suggestion.match_confidence == null || suggestion.match_confidence < CONFIDENCE_UNCERTAIN_BELOW
}

const stats = computed(() => {
  const createdToday = suggestions.value.filter((s) => isToday(s.created_at))
  return {
    newToday: createdToday.length,
    confirmedToday: createdToday.filter((s) => s.status === 'confirmed').length,
    uncertain: pendingSuggestions.value.filter(isUncertain).length,
    overdue: pendingSuggestions.value.filter(
      (s) => now.value - new Date(s.created_at).getTime() > 30 * 60 * 1000,
    ).length,
  }
})

function formatDateTime(iso) {
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}
function minutesAgo(iso) {
  const mins = Math.round((now.value - new Date(iso).getTime()) / 60_000)
  if (mins < 1) return 'только что'
  if (mins < 60) return `${mins} мин назад`
  const hours = Math.round(mins / 60)
  return `${hours} ч назад`
}

// Пока в модели только Telegram (TriageChannel — см. apps/triage/models.py
// докстринг: WhatsApp сознательно не заведён), поэтому иконка/цвет для
// него единственные настоящие; неизвестный канал получает нейтральную
// подпись вместо выдуманной иконки.
const CHANNEL_LABELS = { telegram: 'Telegram' }

// ---- Действия над предложением ----------------------------------------
const actionRowId = ref(null)
const actionKind = ref(null) // 'confirm' | 'change' | 'reject'
const actionError = ref('')
const actionSubmitting = ref(false)
const rejectReason = ref('')

const patientQuery = ref('')
const patientResults = ref([])
const patientSearching = ref(false)
const selectedPatient = ref(null)
let searchTimer = null

const changeDoctors = ref([])
const changeDoctorsError = ref('')
const changeDoctorsLoading = ref(false)
const selectedDoctorId = ref(null)
const slotsByDate = ref({})
const slotsLoading = ref(false)
const selectedSlot = ref(null)

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

function closeAction() {
  actionRowId.value = null
  actionKind.value = null
  actionError.value = ''
  rejectReason.value = ''
  patientQuery.value = ''
  patientResults.value = []
  selectedPatient.value = null
  changeDoctors.value = []
  changeDoctorsError.value = ''
  selectedDoctorId.value = null
  slotsByDate.value = {}
  selectedSlot.value = null
}

async function openAction(suggestion, kind) {
  closeAction()
  actionRowId.value = suggestion.id
  actionKind.value = kind
  if ((kind === 'confirm' || kind === 'change') && suggestion.matched_patient_candidate) {
    patientQuery.value = suggestion.contact_phone || ''
  }
  if (kind === 'change') {
    changeDoctorsLoading.value = true
    try {
      const { data } = await doctorsApi.list({ branch: suggestion.branch })
      changeDoctors.value = data
    } catch {
      changeDoctorsError.value = 'Не удалось загрузить список врачей филиала.'
    } finally {
      changeDoctorsLoading.value = false
    }
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
function selectSlot(slot) {
  selectedSlot.value = selectedSlot.value?.starts_at === slot.starts_at ? null : slot
}
const hasAnySlot = computed(() => Object.values(slotsByDate.value).some((slots) => slots.length > 0))

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

async function submitChange(suggestion) {
  if (!selectedPatient.value) {
    actionError.value = 'Выберите пациента из списка.'
    return
  }
  if (!selectedDoctorId.value || !selectedSlot.value) {
    actionError.value = 'Выберите врача и свободный слот.'
    return
  }
  actionError.value = ''
  actionSubmitting.value = true
  try {
    await triageApi.confirm(suggestion.id, selectedPatient.value.id, {
      doctor: selectedDoctorId.value,
      startsAt: selectedSlot.value.starts_at,
      endsAt: selectedSlot.value.ends_at,
    })
    closeAction()
    await load()
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось подтвердить на новый слот.'
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
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Очередь триажа</h1>
        <div class="meta">Вся сеть · AI-бот Telegram</div>
      </div>
    </div>

    <div v-if="loadError" class="content"><p style="font-size:13px;color:var(--red)">{{ loadError }}</p></div>

    <div v-else class="content">
      <div class="stats-row">
        <div class="stat"><div class="stat-label">Новых сегодня</div><div class="stat-value">{{ stats.newToday }}</div></div>
        <div class="stat"><div class="stat-label">Подтверждено сегодня</div><div class="stat-value">{{ stats.confirmedToday }}</div></div>
        <div class="stat"><div class="stat-label">Требуют уточнения</div><div class="stat-value">{{ stats.uncertain }}</div></div>
        <div class="stat">
          <div class="stat-label">Ожидают &gt; 30 мин</div>
          <div class="stat-value" :style="stats.overdue > 0 ? { color: 'var(--red)' } : {}">{{ stats.overdue }}</div>
        </div>
      </div>

      <div class="section-label">Ожидают подтверждения</div>
      <div class="queue">
        <div
          v-for="suggestion in pendingSuggestions"
          :key="suggestion.id"
          class="suggestion"
          :class="isUncertain(suggestion) ? 'uncertain' : 'new'"
        >
          <div class="patient-col">
            <div class="channel">
              <span class="channel-icon">{{ (CHANNEL_LABELS[suggestion.channel] || suggestion.channel || '?')[0] }}</span>
              {{ CHANNEL_LABELS[suggestion.channel] || suggestion.channel }}
            </div>
            <div class="patient-name">{{ suggestion.contact_name || 'Без имени' }}</div>
            <div class="patient-time mono">{{ formatTime(suggestion.created_at) }} · {{ minutesAgo(suggestion.created_at) }}</div>
          </div>

          <div class="middle-col">
            <div class="complaint">«{{ suggestion.symptom_text }}»</div>
            <div class="suggestion-row">
              <span class="tag spec">{{ suggestion.specialty_name }}</span>
              <span class="tag slot">{{ formatDateTime(suggestion.suggested_starts_at) }} · {{ suggestion.doctor_name }}</span>
              <span class="tag confidence" :class="{ low: isUncertain(suggestion) }">
                {{ suggestion.match_confidence != null ? `увер. ${suggestion.match_confidence}%` : 'увер. н/д' }}
                <template v-if="isUncertain(suggestion)">— уточнить</template>
              </span>
            </div>

            <template v-if="actionRowId === suggestion.id">
              <div v-if="actionKind === 'confirm' || actionKind === 'change'" style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
                <p v-if="suggestion.matched_patient_candidate" style="font-size:11.5px;color:var(--ink-soft)">
                  Похоже на существующего пациента:
                  <span class="tag slot" style="cursor:pointer" @click="pickCandidate(suggestion)">
                    {{ suggestion.matched_patient_candidate.name }} — выбрать
                  </span>
                </p>
                <div>
                  <div class="field-label">Пациент (имя или телефон)</div>
                  <input v-model="patientQuery" class="select-field" placeholder="Иванов или +996..." />
                </div>
                <p v-if="patientSearching" style="font-size:11.5px;color:var(--ink-soft)">Ищем…</p>
                <ul v-else-if="patientResults.length" style="border:1px solid var(--line);border-radius:8px;max-height:140px;overflow-y:auto">
                  <li
                    v-for="patient in patientResults"
                    :key="patient.id"
                    style="padding:6px 10px;font-size:12.5px;cursor:pointer;border-bottom:1px solid #F1EEE6"
                    @click="pickPatient(patient)"
                  >
                    {{ patient.first_name }} {{ patient.last_name }}
                    <span style="color:var(--ink-soft);font-size:11px">{{ patient.phone }}</span>
                  </li>
                </ul>
                <p v-if="selectedPatient" style="font-size:11.5px;color:var(--mint-d)">
                  Выбран: {{ selectedPatient.first_name }} {{ selectedPatient.last_name }}
                </p>

                <template v-if="actionKind === 'change'">
                  <p v-if="changeDoctorsError" style="font-size:12.5px;color:var(--red)">{{ changeDoctorsError }}</p>
                  <div v-else>
                    <div class="field-label">Врач — «{{ suggestion.branch_name }}»</div>
                    <select v-model="selectedDoctorId" class="select-field">
                      <option :value="null" disabled>{{ changeDoctorsLoading ? 'Загружаем…' : 'Выберите врача…' }}</option>
                      <option v-for="doctor in changeDoctors" :key="doctor.id" :value="doctor.id">
                        {{ doctor.display_name }}
                      </option>
                    </select>
                  </div>

                  <div v-if="selectedDoctorId">
                    <div class="field-label">Свободные слоты</div>
                    <p v-if="slotsLoading" style="font-size:11.5px;color:var(--ink-soft)">Загружаем слоты…</p>
                    <p v-else-if="!hasAnySlot" style="font-size:11.5px;color:var(--ink-soft)">Свободных окон не найдено на ближайшие 3 дня.</p>
                    <template v-else>
                      <div v-for="date in dates" :key="date" style="margin-bottom:4px">
                        <p v-if="slotsByDate[date]?.length" style="font-size:10.5px;color:var(--ink-soft);margin-bottom:2px">{{ date }}</p>
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
                </template>

                <div style="display:flex;gap:8px">
                  <button
                    v-if="actionKind === 'confirm'"
                    class="btn btn-confirm"
                    :disabled="actionSubmitting || !selectedPatient"
                    @click="submitConfirm(suggestion)"
                  >
                    Подтвердить запись
                  </button>
                  <button
                    v-else
                    class="btn btn-confirm"
                    :disabled="actionSubmitting || !selectedPatient || !selectedSlot"
                    @click="submitChange(suggestion)"
                  >
                    Подтвердить на новый слот
                  </button>
                  <button class="btn btn-change" @click="closeAction">Отмена</button>
                </div>
              </div>

              <div v-else-if="actionKind === 'reject'" style="display:flex;gap:8px;align-items:flex-end;margin-top:4px">
                <div style="flex:1">
                  <div class="field-label">Причина отказа (необязательно)</div>
                  <input v-model="rejectReason" class="select-field" />
                </div>
                <button class="btn btn-decline" :disabled="actionSubmitting" @click="submitReject(suggestion)">Отклонить</button>
                <button class="btn btn-change" @click="closeAction">Отмена</button>
              </div>

              <p v-if="actionError" style="font-size:11.5px;color:var(--red);margin-top:4px">{{ actionError }}</p>
            </template>
          </div>

          <div class="actions-col" v-if="actionRowId !== suggestion.id">
            <button class="btn btn-confirm" @click="openAction(suggestion, 'confirm')">Подтвердить слот</button>
            <button class="btn btn-change" @click="openAction(suggestion, 'change')">Изменить слот</button>
            <button class="btn btn-decline" @click="openAction(suggestion, 'reject')">Отклонить</button>
          </div>
        </div>

        <div v-if="pendingSuggestions.length === 0" class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
          Новых предложений от бота нет.
        </div>
      </div>

      <div class="section-label">Недавно обработано</div>
      <div class="queue">
        <div v-for="suggestion in historySuggestions" :key="suggestion.id" class="suggestion history">
          <div class="patient-col">
            <div class="channel">
              <span class="channel-icon">{{ (CHANNEL_LABELS[suggestion.channel] || suggestion.channel || '?')[0] }}</span>
              {{ CHANNEL_LABELS[suggestion.channel] || suggestion.channel }}
            </div>
            <div class="patient-name">{{ suggestion.contact_name || 'Без имени' }}</div>
            <div class="patient-time mono">{{ formatTime(suggestion.updated_at) }}</div>
          </div>
          <div class="middle-col">
            <div class="suggestion-row">
              <span class="tag spec">{{ suggestion.specialty_name }}</span>
              <span class="tag slot">{{ suggestion.status === 'confirmed' ? formatDateTime(suggestion.suggested_starts_at) + ' · ' + suggestion.doctor_name : '—' }}</span>
            </div>
          </div>
          <div class="actions-col">
            <span v-if="suggestion.status === 'confirmed'" class="status-pill confirmed">✓ Подтверждено</span>
            <span v-else-if="suggestion.status === 'rejected'" class="status-pill declined">
              ✕ Отклонено<template v-if="suggestion.rejection_reason"> — {{ suggestion.rejection_reason }}</template>
            </span>
            <span v-else class="status-pill expired">Слот истёк</span>
          </div>
        </div>

        <div v-if="historySuggestions.length === 0" class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
          Обработанных предложений пока нет.
        </div>
      </div>
    </div>
  </div>
</template>
