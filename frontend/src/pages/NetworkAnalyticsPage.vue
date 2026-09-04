<script setup>
import { computed, onMounted, ref } from 'vue'

import { appointmentsApi, financeReportApi } from '../api'

function isoDate(d) {
  return d.toISOString().slice(0, 10)
}
function daysAgo(n) {
  return isoDate(new Date(Date.now() - n * 24 * 60 * 60 * 1000))
}

function formatMoney(v) {
  return `${Number(v).toLocaleString('ru-RU')} ⃀`
}

// Воронка "обращения → записались → пришли → начали лечение" из макета
// не воспроизводима честно: "обращения"/лиды и "начал лечение" — CRM-
// понятия, которых в бэкенде нет вообще (это клиническая система, не
// CRM с трекингом лидов). Единственные два реальных, проверяемых этапа
// из Appointment — запланировано / состоялось (status=completed).
const funnelError = ref('')
const funnelLoading = ref(true)
const totalAppointments = ref(0)
const completedAppointments = ref(0)

async function loadFunnel() {
  funnelError.value = ''
  funnelLoading.value = true
  try {
    const params = { date_from: daysAgo(30), date_to: isoDate(new Date()) }
    const [allRes, completedRes] = await Promise.all([
      appointmentsApi.list(params),
      appointmentsApi.list({ ...params, status: 'completed' }),
    ])
    totalAppointments.value = (allRes.data.results ?? allRes.data).length
    completedAppointments.value = (completedRes.data.results ?? completedRes.data).length
  } catch {
    funnelError.value = 'Недоступно (нет appointment.view).'
  } finally {
    funnelLoading.value = false
  }
}

const funnelStages = computed(() => {
  if (totalAppointments.value === 0) return []
  return [
    { label: 'Запланировано', count: totalAppointments.value, pct: 100 },
    {
      label: 'Состоялось (завершено)',
      count: completedAppointments.value,
      pct: Math.round((completedAppointments.value / totalAppointments.value) * 100),
    },
  ]
})

// Выручка по неделям — 4 отдельных FinanceReportView-запроса (у него
// нет группировки по неделе, только по филиалу за диапазон дат), тот же
// endpoint, что "Дашборд сети" уже использует для дня/недели-назад.
const weeklyRevenue = ref([])
const revenueError = ref('')
const revenueLoading = ref(true)

async function loadWeeklyRevenue() {
  revenueError.value = ''
  revenueLoading.value = true
  try {
    const windows = [0, 1, 2, 3].map((weeksAgo) => ({
      from: daysAgo((weeksAgo + 1) * 7 - 1),
      to: daysAgo(weeksAgo * 7),
    })).reverse()
    const results = await Promise.all(
      windows.map((w) => financeReportApi.get({ date_from: w.from, date_to: w.to })),
    )
    weeklyRevenue.value = results.map((r, i) => ({
      label: `Нед. ${i + 1}`,
      total: Number(r.data.network_total),
    }))
  } catch {
    revenueError.value = 'Недоступно (нет finance.view).'
  } finally {
    revenueLoading.value = false
  }
}

const maxWeekly = computed(() => Math.max(1, ...weeklyRevenue.value.map((w) => w.total)))

// LTV-когорты — apps.finance.views.LtvCohortReportView, ALL-scope
// finance.view only (см. её докстринг).
const cohorts = ref([])
const cohortsError = ref('')
const cohortsLoading = ref(true)

async function loadCohorts() {
  cohortsError.value = ''
  cohortsLoading.value = true
  try {
    const { data } = await financeReportApi.ltvCohorts()
    cohorts.value = data
  } catch (e) {
    cohortsError.value =
      e.response?.status === 403
        ? 'Недоступно — нужен сетевой (ALL-scope) грант finance.view.'
        : 'Не удалось загрузить когорты.'
  } finally {
    cohortsLoading.value = false
  }
}

onMounted(() => {
  loadFunnel()
  loadWeeklyRevenue()
  loadCohorts()
})
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Аналитика сети</h1>
        <div class="meta">Все филиалы · последние 30 дней</div>
      </div>
    </div>

    <div class="content">
      <div class="grid-2">
        <div class="panel">
          <h3>Воронка приёма (сеть, 30 дней)</h3>
          <p v-if="funnelError" style="font-size:12.5px;color:var(--red)">{{ funnelError }}</p>
          <template v-else-if="!funnelLoading">
            <div v-for="stage in funnelStages" :key="stage.label" class="funnel-row">
              <div class="funnel-label">{{ stage.label }}</div>
              <div class="funnel-bar" :style="{ width: stage.pct + '%' }">
                {{ stage.count }} <span class="funnel-num">{{ stage.pct }}%</span>
              </div>
            </div>
            <p v-if="funnelStages.length === 0" style="font-size:12.5px;color:var(--ink-soft)">
              Приёмов за 30 дней не найдено.
            </p>
          </template>
        </div>

        <div class="panel">
          <h3>Выручка по неделям</h3>
          <p v-if="revenueError" style="font-size:12.5px;color:var(--red)">{{ revenueError }}</p>
          <template v-else-if="!revenueLoading">
            <div class="trend-row">
              <div
                v-for="week in weeklyRevenue"
                :key="week.label"
                class="trend-bar"
                :style="{ height: Math.max(4, Math.round((week.total / maxWeekly) * 100)) + '%' }"
              >
                <span class="cap">{{ (week.total / 1000).toFixed(1) }}К</span>
              </div>
            </div>
            <div class="trend-lbl"><span v-for="week in weeklyRevenue" :key="week.label">{{ week.label }}</span></div>
          </template>
        </div>
      </div>

      <div class="panel">
        <h3>LTV когорты пациентов (по кварталу первого визита)</h3>
        <p v-if="cohortsError" style="font-size:12.5px;color:var(--ink-soft)">{{ cohortsError }}</p>
        <template v-else-if="!cohortsLoading">
          <div v-for="cohort in cohorts" :key="cohort.quarter" class="cohort-row">
            <span>{{ cohort.quarter }} · {{ cohort.patient_count }} пациент(ов)</span>
            <span class="mono">{{ formatMoney(cohort.avg_ltv) }} / пациент · {{ cohort.avg_visits }} визита</span>
          </div>
          <p v-if="cohorts.length === 0" style="font-size:12.5px;color:var(--ink-soft)">Данных по когортам пока нет.</p>
        </template>
      </div>
    </div>
  </div>
</template>
