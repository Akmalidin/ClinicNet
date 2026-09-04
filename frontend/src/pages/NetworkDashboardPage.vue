<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { appointmentsApi, churnApi, financeReportApi, referralsApi, staffApi, stocksApi, visitsApi } from '../api'

function isoDate(d) {
  return d.toISOString().slice(0, 10)
}
const today = isoDate(new Date())
const lastWeek = isoDate(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000))

function formatMoney(v) {
  return `${Number(v).toLocaleString('ru-RU')} ⃀`
}

// Каждая панель — независимый запрос со своим RBAC-грантом (finance.view/
// appointment.view/visit.view/churn.view/inventory.view/staff.view_network/
// referrals.view — семь разных прав), тот же принцип, что везде в проекте:
// нет одной "видит весь дашборд/не видит ничего" развилки, у каждой карточки
// свой независимый источник и своя честная ошибка, если гранта нет.
const revenue = ref(null)
const revenueError = ref('')
const utilization = ref(null)
const utilizationError = ref('')
const inVisitCount = ref(null)
const visitsError = ref('')
const churnNewCount = ref(null)
const churnError = ref('')
const lowStock = ref([])
const lowStockError = ref('')
const licenseAlerts = ref([])
const staffError = ref('')
const pendingReferrals = ref([])
const referralsError = ref('')

async function loadRevenue() {
  revenueError.value = ''
  try {
    const [todayRes, lastWeekRes] = await Promise.all([
      financeReportApi.get({ date_from: today, date_to: today }),
      financeReportApi.get({ date_from: lastWeek, date_to: lastWeek }),
    ])
    revenue.value = {
      byBranch: todayRes.data.by_branch,
      total: Number(todayRes.data.network_total),
      lastWeekTotal: Number(lastWeekRes.data.network_total),
    }
  } catch {
    revenueError.value = 'Недоступно (нет finance.view).'
  }
}
async function loadUtilization() {
  utilizationError.value = ''
  try {
    const { data } = await appointmentsApi.utilization(today)
    utilization.value = data
  } catch {
    utilizationError.value = 'Недоступно (нет appointment.view).'
  }
}
async function loadVisits() {
  visitsError.value = ''
  try {
    const { data } = await visitsApi.list({ status: 'in_progress' })
    inVisitCount.value = (data.results ?? data).length
  } catch {
    visitsError.value = 'Недоступно (нет visit.view).'
  }
}
async function loadChurn() {
  churnError.value = ''
  try {
    const { data } = await churnApi.list()
    const rows = data.results ?? data
    churnNewCount.value = rows.filter((r) => r.status === 'new').length
  } catch {
    churnError.value = 'Недоступно (нет churn.view).'
  }
}
async function loadLowStock() {
  lowStockError.value = ''
  try {
    const { data } = await stocksApi.lowStock()
    lowStock.value = data.results ?? data
  } catch {
    lowStockError.value = 'inventory.view'
  }
}
async function loadStaffAlerts() {
  staffError.value = ''
  try {
    const { data } = await staffApi.list()
    licenseAlerts.value = (data.results ?? data).filter(
      (s) => s.license_status === 'warning' || s.license_status === 'expired',
    )
  } catch {
    staffError.value = 'staff.view_network'
  }
}
async function loadReferrals() {
  referralsError.value = ''
  try {
    const { data } = await referralsApi.list({ status: 'pending' })
    pendingReferrals.value = data.results ?? data
  } catch {
    referralsError.value = 'Недоступно (нет referrals.view).'
  }
}

onMounted(() => {
  loadRevenue()
  loadUtilization()
  loadVisits()
  loadChurn()
  loadLowStock()
  loadStaffAlerts()
  loadReferrals()
})

const revenueDeltaPercent = computed(() => {
  if (!revenue.value || !revenue.value.lastWeekTotal) return null
  return Math.round(((revenue.value.total - revenue.value.lastWeekTotal) / revenue.value.lastWeekTotal) * 1000) / 10
})

const branchBars = computed(() => {
  if (!revenue.value) return []
  const rows = revenue.value.byBranch
  const max = Math.max(1, ...rows.map((r) => Number(r.net)))
  return rows
    .map((r) => ({ ...r, net: Number(r.net), pct: Math.round((Number(r.net) / max) * 100) }))
    .sort((a, b) => b.net - a.net)
})

// Часы просрочки, не выдуманный "SLA" — просто created_at направления
// старше суток и всё ещё pending, тот же признак, что escalate_stale_
// referrals уже использует бэкендом (apps.referrals.services).
const staleReferrals = computed(() =>
  pendingReferrals.value.filter((r) => Date.now() - new Date(r.created_at).getTime() > 24 * 60 * 60 * 1000),
)
const crossBranchReferrals = computed(() =>
  pendingReferrals.value.filter((r) => r.from_branch !== r.to_branch).slice(0, 5),
)

const alerts = computed(() => {
  const rows = []
  for (const stock of lowStock.value) {
    rows.push({
      severity: Number(stock.on_hand_quantity) <= 0 ? 'crit' : 'warn',
      title: `${stock.branch_name}: остаток «${stock.product_name}» ниже минимума`,
      sub: `Склад · ${stock.on_hand_quantity} ${stock.product_unit} (мин. ${stock.min_quantity})`,
    })
  }
  for (const staff of licenseAlerts.value) {
    rows.push({
      severity: staff.license_status === 'expired' ? 'crit' : 'warn',
      title: `Лицензия ${staff.name} — ${staff.license_status === 'expired' ? 'истекла' : 'скоро истекает'}`,
      sub: `Персонал · ${staff.branches?.join(', ') || ''}`,
    })
  }
  if (staleReferrals.value.length > 0) {
    rows.push({
      severity: 'warn',
      title: `${staleReferrals.value.length} направлени${staleReferrals.value.length === 1 ? 'е' : 'й'} ожидают > 24 часов`,
      sub: 'Координация',
    })
  }
  return rows
})

function initials(name) {
  return (name || '').split(' ').map((s) => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div>
        <h1>Дашборд сети</h1>
        <div class="meta">Обновлено сегодня</div>
      </div>
    </div>

    <div class="content">
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Выручка сегодня</div>
          <template v-if="revenueError"><div style="font-size:12px;color:var(--red)">{{ revenueError }}</div></template>
          <template v-else-if="revenue">
            <div class="kpi-value">{{ formatMoney(revenue.total) }}</div>
            <div v-if="revenueDeltaPercent != null" class="kpi-delta" :class="revenueDeltaPercent >= 0 ? 'up' : 'down'">
              {{ revenueDeltaPercent >= 0 ? '▲' : '▼' }} {{ Math.abs(revenueDeltaPercent) }}% к прошлой неделе (тот же день)
            </div>
          </template>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Загрузка врачей</div>
          <template v-if="utilizationError"><div style="font-size:12px;color:var(--red)">{{ utilizationError }}</div></template>
          <template v-else-if="utilization">
            <div class="kpi-value">{{ utilization.utilization_percent != null ? utilization.utilization_percent + '%' : '—' }}</div>
            <div class="kpi-delta" style="color:var(--ink-soft)">
              {{ utilization.booked_minutes }} из {{ utilization.available_minutes }} мин по сменам
            </div>
          </template>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Пациентов на приёме</div>
          <template v-if="visitsError"><div style="font-size:12px;color:var(--red)">{{ visitsError }}</div></template>
          <template v-else><div class="kpi-value">{{ inVisitCount ?? '—' }}</div></template>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Риск оттока (AI)</div>
          <template v-if="churnError"><div style="font-size:12px;color:var(--red)">{{ churnError }}</div></template>
          <template v-else>
            <div class="kpi-value">{{ churnNewCount ?? '—' }}</div>
            <div class="kpi-delta" style="color:var(--ink-soft)">пациентов требуют реактивации</div>
          </template>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-head"><h3>Выручка по филиалам</h3></div>
          <p v-if="revenueError" style="font-size:12.5px;color:var(--ink-soft)">{{ revenueError }}</p>
          <template v-else>
            <div v-for="row in branchBars" :key="row.branch_id" class="branch-row">
              <div class="branch-name">{{ row.branch_name }}</div>
              <div class="branch-bar-track"><div class="branch-bar-fill" :style="{ width: row.pct + '%' }"></div></div>
              <div class="branch-val">{{ formatMoney(row.net) }}</div>
            </div>
            <p v-if="branchBars.length === 0" style="font-size:12.5px;color:var(--ink-soft)">Платежей сегодня нет.</p>
          </template>
        </div>

        <div class="panel">
          <div class="panel-head"><h3>Требует внимания</h3><span class="link">Всего — {{ alerts.length }}</span></div>
          <div v-for="(alert, i) in alerts.slice(0, 6)" :key="i" class="alert">
            <div class="alert-badge" :class="alert.severity"></div>
            <div>
              <div class="alert-title">{{ alert.title }}</div>
              <div class="alert-sub">{{ alert.sub }}</div>
            </div>
          </div>
          <p v-if="alerts.length === 0" style="font-size:12.5px;color:var(--ink-soft)">Активных алертов нет.</p>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h3>Направления между филиалами</h3>
          <RouterLink :to="{ name: 'dashboard' }" class="link" style="text-decoration:none">Открыть очередь →</RouterLink>
        </div>
        <p v-if="referralsError" style="font-size:12.5px;color:var(--ink-soft)">{{ referralsError }}</p>
        <div v-else style="overflow-x:auto">
          <table>
            <thead>
              <tr><th>Пациент</th><th>От кого</th><th>Кому / куда</th><th>Причина</th><th>Статус</th></tr>
            </thead>
            <tbody>
              <tr v-for="ref in crossBranchReferrals" :key="ref.id">
                <td>{{ ref.patient_name }}</td>
                <td class="doc-cell"><span class="avatar" style="width:26px;height:26px;font-size:10.5px">{{ initials(ref.from_doctor_name) }}</span> {{ ref.from_doctor_name }} · {{ ref.from_branch_name }}</td>
                <td>{{ ref.to_doctor_name || ref.to_specialty_name || '—' }} · {{ ref.to_branch_name }}</td>
                <td>{{ ref.reason }}</td>
                <td><span class="pill wait">Ожидает</span></td>
              </tr>
              <tr v-if="crossBranchReferrals.length === 0">
                <td colspan="5" style="text-align:center;color:var(--ink-soft);padding:20px">Межфилиальных направлений в ожидании нет.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
