<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { appointmentsApi } from '../api'

function toIsoDate(d) {
  return d.toISOString().slice(0, 10)
}

const selectedDate = ref(toIsoDate(new Date()))
const selectedBranchId = ref(null) // null = все филиалы

const appointments = ref([])
const loadError = ref('')
const loading = ref(false)

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    const { data } = await appointmentsApi.list({ date: selectedDate.value })
    appointments.value = data.results ?? data
  } catch {
    loadError.value = 'Не удалось загрузить расписание по сети.'
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(selectedDate, load)

function shiftDate(days) {
  const d = new Date(selectedDate.value + 'T00:00:00')
  d.setDate(d.getDate() + days)
  selectedDate.value = toIsoDate(d)
}
function goToday() {
  selectedDate.value = toIsoDate(new Date())
}

const formattedDate = computed(() => {
  const d = new Date(selectedDate.value + 'T00:00:00')
  return d.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })
})

// Ветки/чипы — не отдельный справочник (branchesApi.directory() отдаёт
// ВЕСЬ каталог сети без учёта appointment.view), а именно те филиалы,
// чьи приёмы реально вернул сегодняшний запрос — так чип показывает
// ровно то, что пользователю и так видно, RBAC-корректно "бесплатно".
const branches = computed(() => {
  const map = new Map()
  for (const appt of appointments.value) {
    if (!map.has(appt.branch)) map.set(appt.branch, appt.branch_display)
  }
  return [...map.entries()].map(([id, name]) => ({ id, name }))
})

const visibleAppointments = computed(() =>
  selectedBranchId.value == null
    ? appointments.value
    : appointments.value.filter((a) => a.branch === selectedBranchId.value),
)

// Часовые колонки — по фактическому разбросу времени приёмов за день
// (не захардкожено 09-18: сеть может работать иначе), с разумным
// запасом по умолчанию, если приёмов ещё нет.
const hours = computed(() => {
  if (visibleAppointments.value.length === 0) return Array.from({ length: 9 }, (_, i) => 9 + i)
  let min = 23
  let max = 0
  for (const appt of visibleAppointments.value) {
    const h = new Date(appt.starts_at).getHours()
    min = Math.min(min, h)
    max = Math.max(max, h)
  }
  return Array.from({ length: max - min + 1 }, (_, i) => min + i)
})

function formatHour(h) {
  return `${String(h).padStart(2, '0')}:00`
}
function formatTimeRange(appt) {
  const fmt = (iso) => new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return `${fmt(appt.starts_at)}–${fmt(appt.ends_at)}`
}

// Цвет — единственный реальный сигнал приоритета в данных: приоритет
// направления (Referral.priority), если приём из направления. Обычные
// (не из направления) приёмы — плановые по умолчанию, честно без
// категорий "консультация/новый пациент", которых в модели нет.
function slotColor(appt) {
  const priority = appt.referral?.priority
  if (priority === 'emergency') return 'red'
  if (priority === 'urgent') return 'amber'
  return 'mint'
}

function initials(name) {
  return name.split(' ').map((s) => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
}

// Отделение по (филиал, врач) → часовой ячейке.
const branchBoards = computed(() =>
  branches.value
    .filter((b) => selectedBranchId.value == null || b.id === selectedBranchId.value)
    .map((branch) => {
      const branchAppts = appointments.value.filter((a) => a.branch === branch.id)
      const doctorMap = new Map()
      for (const appt of branchAppts) {
        if (!doctorMap.has(appt.doctor)) {
          doctorMap.set(appt.doctor, { id: appt.doctor, name: appt.doctor_display, appts: [] })
        }
        doctorMap.get(appt.doctor).appts.push(appt)
      }
      const doctors = [...doctorMap.values()].map((doc) => {
        const byHour = {}
        for (const appt of doc.appts) {
          const h = new Date(appt.starts_at).getHours()
          byHour[h] = byHour[h] ?? []
          byHour[h].push(appt)
        }
        return { ...doc, byHour }
      })
      return { ...branch, doctors, count: doctors.length }
    }),
)
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Расписание по сети</h1>
        <div class="meta">{{ formattedDate }} · {{ branchBoards.length }} филиал(ов) показано</div>
      </div>
    </div>

    <div class="toolbar">
      <div class="chip" :class="{ active: selectedBranchId == null }" @click="selectedBranchId = null">Все филиалы</div>
      <div
        v-for="branch in branches"
        :key="branch.id"
        class="chip"
        :class="{ active: selectedBranchId === branch.id }"
        @click="selectedBranchId = branch.id"
      >
        {{ branch.name }}
      </div>
      <div class="spacer"></div>
      <div class="date-nav">
        <button @click="shiftDate(-1)">‹</button>
        <span>{{ selectedDate }}</span>
        <button @click="shiftDate(1)">›</button>
      </div>
      <button class="today-btn" @click="goToday">Сегодня</button>
    </div>

    <div class="sched-legend">
      <span><span class="sw" style="background:var(--mint-l);border:1px solid var(--mint)"></span> Приём</span>
      <span><span class="sw" style="background:var(--amber-l);border:1px solid var(--amber)"></span> Направление — срочное</span>
      <span><span class="sw" style="background:var(--red-l);border:1px solid var(--red)"></span> Направление — экстренное</span>
    </div>

    <p v-if="loadError" style="padding:16px 32px;font-size:13px;color:var(--red)">{{ loadError }}</p>

    <div v-else class="board">
      <div v-for="branch in branchBoards" :key="branch.id" class="branch-block">
        <div class="branch-head">
          <h3>{{ branch.name }}</h3>
          <span class="cnt">{{ branch.count }} врач(ей) в этот день</span>
        </div>
        <div class="grid" :style="{ gridTemplateColumns: `150px repeat(${hours.length}, 1fr)` }">
          <div class="hcell">Врач</div>
          <div v-for="h in hours" :key="h" class="hcell">{{ formatHour(h) }}</div>

          <template v-for="doctor in branch.doctors" :key="doctor.id">
            <div class="doc-name">
              <div class="doc-avatar">{{ initials(doctor.name) }}</div>
              <div class="doc-meta"><div class="n">{{ doctor.name }}</div></div>
            </div>
            <div v-for="h in hours" :key="h" :class="doctor.byHour[h] ? '' : 'empty-cell'">
              <div v-for="appt in doctor.byHour[h] ?? []" :key="appt.id" class="slot" :class="slotColor(appt)">
                {{ appt.patient_display }}
                <div class="t">{{ formatTimeRange(appt) }}</div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <div v-if="!loading && branchBoards.length === 0" class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
        На эту дату приёмов не найдено.
      </div>
    </div>
  </div>
</template>
