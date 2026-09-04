<script setup>
import { computed, onMounted, ref } from 'vue'

import { churnApi } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const risks = ref([])
const loadError = ref('')
const droppedCount = ref(0)
const actionSubmitting = ref(null) // id currently in flight

function isVisible(risk) {
  return auth.churnBranches.includes(risk.branch)
}

async function load() {
  loadError.value = ''
  try {
    const { data } = await churnApi.list()
    const rows = data.results ?? data
    const visible = rows.filter(isVisible)
    droppedCount.value = rows.length - visible.length
    if (droppedCount.value > 0) {
      // eslint-disable-next-line no-console
      console.error(
        `ChurnAlertsPage: dropped ${droppedCount.value} row(s) that failed the client-side ` +
          'branch guard — the backend returned risks outside what /me/ says this user can see.',
      )
    }
    risks.value = visible
  } catch {
    loadError.value = 'Не удалось загрузить риск оттока.'
  }
}
onMounted(load)

const activeRisks = computed(() =>
  risks.value.filter((r) => r.status === 'new' || r.status === 'acknowledged').sort((a, b) => b.risk_score - a.risk_score),
)

const stats = computed(() => {
  const monthAgo = Date.now() - 30 * 24 * 60 * 60 * 1000
  return {
    atRisk: activeRisks.value.length,
    contacted: risks.value.filter((r) => r.status === 'acknowledged').length,
    reactivatedThisMonth: risks.value.filter(
      (r) => r.status === 'reactivated' && new Date(r.updated_at).getTime() >= monthAgo,
    ).length,
  }
})

function riskTier(score) {
  if (score >= 2) return { label: 'высокий риск', color: 'var(--red)' }
  if (score >= 1) return { label: 'средний риск', color: 'var(--amber)' }
  return { label: 'низкий риск', color: 'var(--mint)' }
}
function riskWidth(score) {
  return `${Math.min(100, Math.round(score * 50))}%`
}

async function acknowledge(risk) {
  actionSubmitting.value = risk.id
  try {
    await churnApi.acknowledge(risk.id)
    await load()
  } finally {
    actionSubmitting.value = null
  }
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div><h1>Риск оттока пациентов</h1><div class="meta">Вся сеть · эвристика по периодичности визитов · обновляется раз в сутки</div></div>
    </div>

    <div v-if="loadError" class="content"><p class="text-sm text-red-600">{{ loadError }}</p></div>

    <div v-else class="content">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">
        <div class="panel" style="padding:16px 18px">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink-soft)">Пациентов в риске</div>
          <div class="mono" style="font-size:24px;font-weight:600;color:var(--navy);margin-top:6px">{{ stats.atRisk }}</div>
        </div>
        <div class="panel" style="padding:16px 18px">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink-soft)">Уже связались</div>
          <div class="mono" style="font-size:24px;font-weight:600;color:var(--navy);margin-top:6px">{{ stats.contacted }}</div>
        </div>
        <div class="panel" style="padding:16px 18px">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink-soft)">Вернулись за месяц</div>
          <div class="mono" style="font-size:24px;font-weight:600;color:var(--mint-d);margin-top:6px">{{ stats.reactivatedThisMonth }}</div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:10px">
        <div
          v-for="risk in activeRisks"
          :key="risk.id"
          class="panel"
          style="padding:15px 18px;display:grid;grid-template-columns:auto 1fr auto auto auto;gap:18px;align-items:center"
        >
          <div class="avatar">{{ risk.patient_name.split(' ').map((s) => s[0]).join('').slice(0, 2).toUpperCase() }}</div>
          <div>
            <div style="font-size:14px;font-weight:600">{{ risk.patient_name }}</div>
            <div style="font-size:11.5px;color:var(--ink-soft);margin-top:2px">
              Обычно раз в {{ Math.round(risk.avg_interval_days) }} дн. · {{ risk.branch_name }}
            </div>
          </div>
          <div style="width:110px">
            <div style="height:8px;background:#EFECE3;border-radius:999px;overflow:hidden">
              <div :style="{ height: '100%', borderRadius: '999px', width: riskWidth(risk.risk_score), background: riskTier(risk.risk_score).color }"></div>
            </div>
            <div class="mono" style="font-size:10.5px;color:var(--ink-soft);margin-top:4px">{{ riskTier(risk.risk_score).label }}</div>
          </div>
          <div class="mono" style="font-size:12.5px;text-align:right">
            <div style="font-weight:700">{{ risk.days_overdue }}</div>
            <div style="font-size:10px;color:var(--ink-soft)">дней просрочки</div>
          </div>
          <div style="display:flex;gap:8px" v-if="risk.patient_phone">
            <a class="btn" style="background:var(--mint);color:#fff;text-decoration:none" :href="`tel:${risk.patient_phone}`">Позвонить</a>
            <button
              v-if="risk.status === 'new'"
              class="btn btn-outline"
              :disabled="actionSubmitting === risk.id"
              @click="acknowledge(risk)"
            >
              В работу
            </button>
          </div>
        </div>

        <div v-if="activeRisks.length === 0" class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
          Активных алертов оттока нет.
        </div>
      </div>
    </div>
  </div>
</template>
