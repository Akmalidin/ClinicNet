<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { admissionsApi } from '../api'

const board = ref(null)
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    const { data } = await admissionsApi.bedBoard()
    board.value = data
  } catch (e) {
    loadError.value =
      e.response?.status === 403
        ? 'Недостаточно прав — нет ни одного отделения, чью занятость можно увидеть.'
        : 'Не удалось загрузить коечный фонд.'
  }
}
onMounted(load)

// "Обновлено в реальном времени" (макет) — честно ограничено до "часы
// тикают, страница не перезапрашивает сама себя": реального live-канала
// (WS/polling) для коечного фонда нет, повторный load() — вручную
// (кнопка «Обновить»), не выдумываем частоту опроса, которой не будет.
const now = ref(new Date())
let clock = null
onMounted(() => {
  clock = setInterval(() => { now.value = new Date() }, 30_000)
})
onUnmounted(() => clearInterval(clock))
const clockLabel = computed(() => now.value.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }))

const STATUS_ORDER = ['occupied', 'reserved', 'cleaning', 'free']
const STATUS_LABELS = { free: 'Свободна', occupied: 'Занята', reserved: 'Резерв (плановая госпитализация)', cleaning: 'Уборка / подготовка' }

const occupancyPercent = computed(() => {
  if (!board.value || !board.value.total_beds) return {}
  const total = board.value.total_beds
  const pct = {}
  for (const status of STATUS_ORDER) {
    pct[status] = Math.round(((board.value.occupancy[status] ?? 0) / total) * 1000) / 10
  }
  return pct
})
const loadPercent = computed(() => {
  if (!board.value || !board.value.total_beds) return 0
  const busy = (board.value.occupancy.occupied ?? 0) + (board.value.occupancy.reserved ?? 0)
  return Math.round((busy / board.value.total_beds) * 100)
})

function roomBedCount(room) {
  return room.beds.length
}
function departmentBedCount(department) {
  return department.rooms.reduce((sum, room) => sum + room.beds.length, 0)
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Коечный фонд</h1>
        <div class="meta">Стационар · вся доступная сеть</div>
      </div>
      <div class="mono" style="font-size:12px;color:var(--ink-soft)">{{ clockLabel }}</div>
    </div>

    <div class="bed-legend">
      <span><span class="sw" style="background:var(--mint)"></span> Свободна</span>
      <span><span class="sw" style="background:var(--red)"></span> Занята</span>
      <span><span class="sw" style="background:var(--amber)"></span> Резерв (плановая госпитализация)</span>
      <span><span class="sw" style="background:var(--slate)"></span> Уборка / подготовка</span>
    </div>

    <div v-if="loadError" class="content"><p style="font-size:13px;color:var(--red)">{{ loadError }}</p></div>

    <div v-else-if="board" class="content">
      <div class="occ-bar">
        <div class="occ-num">Загрузка: {{ loadPercent }}%</div>
        <div class="occ-track">
          <div
            v-for="status in STATUS_ORDER"
            :key="status"
            class="occ-seg"
            :class="status"
            :style="{ width: (occupancyPercent[status] ?? 0) + '%' }"
            :title="`${STATUS_LABELS[status]}: ${board.occupancy[status] ?? 0}`"
          ></div>
        </div>
        <div class="occ-num">{{ (board.occupancy.occupied ?? 0) + (board.occupancy.reserved ?? 0) }} / {{ board.total_beds }} коек</div>
      </div>

      <div v-for="department in board.departments" :key="department.id" class="dept-block">
        <div class="dept-head">
          <h3>{{ department.name }} — {{ department.branch_name }}</h3>
          <span class="cnt">{{ departmentBedCount(department) }} коек · {{ department.rooms.length }} палат</span>
        </div>
        <div class="rooms">
          <div v-for="room in department.rooms" :key="room.id" class="room">
            <div class="room-head">
              <span class="room-name">Палата {{ room.name }}</span>
              <span class="room-cnt mono">{{ roomBedCount(room) }} коек</span>
            </div>
            <div class="beds">
              <template v-for="bed in room.beds" :key="bed.id">
                <RouterLink
                  v-if="bed.admission_id"
                  :to="{ name: 'vitals-chart', params: { id: bed.admission_id } }"
                  class="bed"
                  :class="bed.status"
                  :title="`${bed.patient_name} — открыть лист наблюдения`"
                  style="text-decoration:none"
                >
                  {{ room.name }}-{{ bed.label }}
                </RouterLink>
                <div
                  v-else
                  class="bed"
                  :class="bed.status"
                  :title="bed.patient_name || STATUS_LABELS[bed.status]"
                >
                  {{ room.name }}-{{ bed.label }}
                </div>
              </template>
            </div>
          </div>
          <p v-if="department.rooms.length === 0" style="font-size:12px;color:var(--ink-soft)">В отделении нет палат.</p>
        </div>
      </div>

      <div v-if="board.departments.length === 0" class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
        Нет ни одного отделения с видимой занятостью.
      </div>
    </div>
  </div>
</template>
