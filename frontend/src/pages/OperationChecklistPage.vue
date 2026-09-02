<script setup>
import { computed, onMounted, ref } from 'vue'

import { operationsApi } from '../api'

// Backend grain is per-PHASE, not per-item (Operation model: three
// {confirmed_by, confirmed_at} pairs, no per-item state — see
// apps.inpatient.models.Operation's docstring). The bullet items below
// are the standard WHO Surgical Safety Checklist text, shown as
// informational context for what a single phase-confirm actually
// attests to; they render as a group (all checked once the phase is
// confirmed), not as individually-clickable checkboxes — there is
// nothing server-side to click them against individually.
const CHECKLIST_ITEMS = {
  sign_in: [
    'Пациент подтвердил личность, место операции, вмешательство и согласие',
    'Место операции промаркировано (где применимо)',
    'Проверка анестезиологического оборудования и медикаментов завершена',
    'Пульсоксиметр на пациенте и работает',
  ],
  time_out: [
    'Все члены бригады представились и назвали свою роль',
    'Подтверждены пациент, место операции и вмешательство',
    'Антибиотикопрофилактика введена за последние 60 минут',
    'Ожидаемые критические моменты озвучены хирургом',
  ],
  sign_out: [
    'Устно подтверждено название выполненной операции',
    'Подсчёт инструментов, игл и салфеток завершён верно',
    'Маркировка операционного материала (образцы) подтверждена',
    'Хирург, анестезиолог и медсестра обозначили ключевые моменты для восстановления пациента',
  ],
}

const PHASES = [
  { key: 'sign_in', label: 'Sign In', title: 'Sign In — перед началом анестезии', action: 'signIn' },
  { key: 'time_out', label: 'Time Out', title: 'Time Out — перед разрезом', action: 'timeOut' },
  { key: 'sign_out', label: 'Sign Out', title: 'Sign Out — перед выходом из операционной', action: 'signOut' },
]

const props = defineProps({ id: { type: [String, Number], required: true } })

const operation = ref(null)
const loadError = ref('')
const actionError = ref('')
const actionSubmitting = ref(false)

async function load() {
  loadError.value = ''
  try {
    const { data } = await operationsApi.get(props.id)
    operation.value = data
  } catch {
    loadError.value = 'Не удалось загрузить операцию.'
  }
}
onMounted(load)

function phaseDoneAt(key) {
  return operation.value?.[`${key}_confirmed_at`] ?? null
}

// The first not-yet-confirmed phase — the only one a user can act on
// right now (phases are strictly sequential, enforced server-side too:
// Operation.confirm_time_out()/confirm_sign_out() refuse out of order).
const activePhaseIndex = computed(() => PHASES.findIndex((p) => !phaseDoneAt(p.key)))
const allPhasesDone = computed(() => activePhaseIndex.value === -1)
const activePhase = computed(() => (allPhasesDone.value ? null : PHASES[activePhaseIndex.value]))

const statusBadge = computed(() => {
  if (!operation.value) return { text: '', done: false }
  if (operation.value.status === 'completed') return { text: 'Завершена', done: true }
  if (operation.value.status === 'cancelled') return { text: 'Отменена', done: false }
  if (allPhasesDone.value) return { text: 'Готова к завершению', done: true }
  return { text: activePhase.value.label, done: false }
})

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

async function confirmPhase() {
  if (!activePhase.value) return
  actionError.value = ''
  actionSubmitting.value = true
  try {
    const { data } = await operationsApi[activePhase.value.action](props.id)
    operation.value = data
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось подтвердить этап.'
  } finally {
    actionSubmitting.value = false
  }
}

async function completeOperation() {
  actionError.value = ''
  actionSubmitting.value = true
  try {
    const { data } = await operationsApi.complete(props.id)
    operation.value = data
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось завершить операцию.'
  } finally {
    actionSubmitting.value = false
  }
}
</script>

<template>
  <div class="mockup-page">
    <div v-if="loadError" class="p-6 text-sm text-red-600">{{ loadError }}</div>

    <template v-else-if="operation">
      <div class="topbar">
        <div>
          <h1>{{ operation.procedure_name }}</h1>
          <div class="meta">
            {{ operation.patient_name }} · {{ operation.operating_room_name }}, {{ operation.branch_name }} ·
            начало {{ formatTime(operation.starts_at) }}
          </div>
        </div>
        <span class="status-badge" :class="{ done: statusBadge.done }">{{ statusBadge.text }}</span>
      </div>

      <div class="op-content">
        <div class="phase-track">
          <div
            v-for="(phase, i) in PHASES"
            :key="phase.key"
            class="phase-step"
            :class="{ done: phaseDoneAt(phase.key), active: i === activePhaseIndex && operation.status === 'scheduled' }"
          >
            <div class="phase-line"></div>
            <div class="circle">{{ phaseDoneAt(phase.key) ? '✓' : i + 1 }}</div>
            <div class="lbl">{{ phase.label }}</div>
          </div>
        </div>

        <div v-if="operation.status === 'cancelled'" class="panel">
          <p class="check-text">Операция отменена — чек-лист больше не активен.</p>
        </div>

        <div v-else-if="activePhase" class="panel">
          <div class="panel-title">
            <span class="n">{{ activePhaseIndex + 1 }}</span>
            <h3>{{ activePhase.title }}</h3>
          </div>

          <div v-for="item in CHECKLIST_ITEMS[activePhase.key]" :key="item" class="check-item">
            <div class="checkbox empty">·</div>
            <div class="check-text">{{ item }}</div>
          </div>

          <div class="team-row">
            <div class="team-chip">
              <span class="team-avatar">{{ operation.lead_surgeon_name?.slice(0, 2).toUpperCase() }}</span>
              {{ operation.lead_surgeon_name }} — хирург
            </div>
            <div v-for="member in operation.team_detail" :key="member.id" class="team-chip">
              <span class="team-avatar">{{ member.name.slice(0, 2).toUpperCase() }}</span>
              {{ member.name }}<template v-if="member.job_title"> — {{ member.job_title }}</template>
            </div>
          </div>

          <button class="btn btn-mint" style="margin-top:16px" :disabled="actionSubmitting" @click="confirmPhase">
            Подтвердить {{ activePhase.label }}
          </button>
        </div>

        <div v-else-if="operation.status === 'completed'" class="panel">
          <p class="check-text">Чек-лист пройден полностью, операция завершена.</p>
        </div>

        <template v-if="operation.status === 'scheduled'">
          <div v-if="!allPhasesDone" class="locked-note">
            🔒 Sign Out будет доступен только после того, как все предыдущие этапы подтверждены
          </div>
          <button class="btn-complete" :disabled="!allPhasesDone || actionSubmitting" @click="completeOperation">
            {{ allPhasesDone ? 'Завершить операцию' : 'Завершить операцию (заблокировано)' }}
          </button>
        </template>

        <p v-if="actionError" class="text-sm" style="color:var(--red)">{{ actionError }}</p>
      </div>
    </template>
  </div>
</template>
