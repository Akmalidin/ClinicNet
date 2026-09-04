<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { insurancePoliciesApi, labOrdersApi, patientsApi, referralsApi, visitsApi } from '../api'
import LabOrderModal from '../components/diagnostics/LabOrderModal.vue'
import LabOrdersSection from '../components/diagnostics/LabOrdersSection.vue'
import ReferralModal from '../components/referrals/ReferralModal.vue'
import { useAuthStore } from '../stores/auth'

const props = defineProps({ id: { type: [String, Number], required: true } })

const auth = useAuthStore()

const patient = ref(null)
const visits = ref([])
const referrals = ref([])
const labOrders = ref([])
const policies = ref([])
const patientError = ref('')
const visitsError = ref('')
const referralsError = ref('')
const labOrdersError = ref('')
const policiesError = ref('')

const activeTab = ref('timeline')

const modalOpen = ref(false)
const activeVisit = ref(null)
const justCreated = ref(null)

const labOrderModalOpen = ref(false)
const activeLabOrderVisit = ref(null)
const labOrdersSection = ref(null)
const labOrderJustCreated = ref(false)

// Same "fetch each independently, RBAC grants don't come bundled"
// discipline as before (visit.view/patient.view can differ) — extended
// to referrals.view/insurance.view/diagnostics.view, all separate grants.
async function loadPatient() {
  patientError.value = ''
  try {
    const { data } = await patientsApi.get(props.id)
    patient.value = data
  } catch {
    patientError.value = 'Не удалось загрузить карточку пациента.'
  }
}
async function loadVisits() {
  visitsError.value = ''
  try {
    const { data } = await visitsApi.list({ patient: props.id })
    visits.value = data.results ?? data
  } catch {
    visitsError.value = 'Приёмы недоступны (недостаточно прав или ошибка загрузки).'
  }
}
async function loadReferrals() {
  referralsError.value = ''
  try {
    const { data } = await referralsApi.list({ patient: props.id })
    referrals.value = data.results ?? data
  } catch {
    referralsError.value = 'Направления недоступны (недостаточно прав или ошибка загрузки).'
  }
}
async function loadLabOrders() {
  labOrdersError.value = ''
  try {
    const { data } = await labOrdersApi.list({ patient: props.id })
    labOrders.value = data.results ?? data
  } catch {
    labOrdersError.value = 'Анализы недоступны (недостаточно прав или ошибка загрузки).'
  }
}
async function loadPolicies() {
  policiesError.value = ''
  try {
    const { data } = await insurancePoliciesApi.list({ patient: props.id, is_active: true })
    policies.value = data.results ?? data
  } catch {
    policiesError.value = ''  // silently absent — insurance.view is an uncommon grant, no need to alarm most roles
  }
}

onMounted(() => {
  loadPatient()
  loadVisits()
  loadReferrals()
  loadLabOrders()
  loadPolicies()
})

function openReferral(visit) {
  activeVisit.value = visit
  justCreated.value = null
  modalOpen.value = true
}
function onCreated(referral) {
  justCreated.value = referral
  loadReferrals()
}
function openLabOrder(visit) {
  activeLabOrderVisit.value = visit
  labOrderJustCreated.value = false
  labOrderModalOpen.value = true
}
async function onLabOrderCreated() {
  labOrderJustCreated.value = true
  await labOrdersSection.value?.load()
  await loadLabOrders()
}

// Unified feed — the mockup's "Лента визитов" mixes visit/referral/lab
// entries by date. Each entry keeps its original row (`raw`) so the
// per-visit action buttons below still have the real object they need.
const timeline = computed(() => {
  const items = [
    ...visits.value.map((v) => ({ type: 'visit', date: v.created_at, raw: v })),
    ...referrals.value.map((r) => ({ type: 'referral', date: r.created_at, raw: r })),
    ...labOrders.value.map((l) => ({ type: 'lab', date: l.created_at, raw: l })),
  ]
  return items.sort((a, b) => new Date(b.date) - new Date(a.date))
})

const lastVisit = computed(() => (visits.value.length ? visits.value[0] : null))
const activePolicy = computed(() => (policies.value.length ? policies.value[0] : null))

function formatDate(iso) {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}
function formatDateTime(iso) {
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
function initials(p) {
  return `${p.first_name?.[0] ?? ''}${p.last_name?.[0] ?? ''}`.toUpperCase()
}
</script>

<template>
  <div class="mockup-page">
    <div v-if="patientError" class="p-6 text-sm text-red-600">{{ patientError }}</div>

    <template v-else-if="patient">
      <div class="topbar">
        <div style="display:flex;align-items:center;gap:16px">
          <RouterLink :to="{ name: 'dashboard' }" style="color:var(--ink-soft);font-size:12px;text-decoration:none">← Пациенты</RouterLink>
          <div class="avatar-lg">{{ initials(patient) }}</div>
          <div>
            <h1>{{ patient.first_name }} {{ patient.last_name }}</h1>
            <div class="meta">
              <template v-if="patient.date_of_birth">{{ patient.date_of_birth }} г.р. · </template>
              <template v-if="activePolicy">Полис ДМС активен · </template>
              история по всей сети
            </div>
          </div>
          <RouterLink
            v-if="auth.admissionDepartments.length"
            :to="{ name: 'admission-intake', params: { id: props.id } }"
            class="btn btn-mint"
            style="margin-left:auto;text-decoration:none"
          >
            Госпитализировать
          </RouterLink>
        </div>
      </div>

      <div v-if="justCreated" class="content" style="padding-bottom:0">
        <div class="panel" style="background:var(--mint-l);border-color:transparent;color:var(--mint-d);font-size:13px">
          Направление создано и отправлено врачу (статус: {{ justCreated.status }}).
        </div>
      </div>
      <div v-if="labOrderJustCreated" class="content" style="padding-bottom:0">
        <div class="panel" style="background:var(--mint-l);border-color:transparent;color:var(--mint-d);font-size:13px">Анализ заказан.</div>
      </div>

      <div class="content" style="display:grid;grid-template-columns:260px 1fr;gap:22px;align-items:start">
        <div style="display:flex;flex-direction:column;gap:16px">
          <div class="panel" style="padding:18px 20px">
            <h3 style="color:var(--navy);margin-bottom:12px">Контакты</h3>
            <div v-if="patient.phone" style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;border-bottom:1px solid #F1EEE6">
              <span style="color:var(--ink-soft)">Телефон</span><span class="mono">{{ patient.phone }}</span>
            </div>
            <div v-if="patient.email" style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;border-bottom:1px solid #F1EEE6">
              <span style="color:var(--ink-soft)">Email</span><span>{{ patient.email }}</span>
            </div>
            <div v-if="lastVisit" style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0">
              <span style="color:var(--ink-soft)">Последний визит</span><span>{{ formatDate(lastVisit.created_at) }}, {{ lastVisit.branch_name }}</span>
            </div>
          </div>

          <div v-if="activePolicy" class="panel" style="padding:18px 20px">
            <h3 style="color:var(--navy);margin-bottom:12px">Полис ДМС</h3>
            <div style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;border-bottom:1px solid #F1EEE6">
              <span style="color:var(--ink-soft)">Страховая</span><span>{{ activePolicy.provider_name }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;border-bottom:1px solid #F1EEE6">
              <span style="color:var(--ink-soft)">Лимит</span><span class="mono">{{ activePolicy.coverage_limit }} ⃀</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0">
              <span style="color:var(--ink-soft)">Использовано</span><span class="mono">{{ activePolicy.used_amount }} ⃀</span>
            </div>
          </div>

          <div class="panel" style="padding:18px 20px">
            <h3 style="color:var(--navy);margin-bottom:12px">Бонусный счёт</h3>
            <div style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;border-bottom:1px solid #F1EEE6">
              <span style="color:var(--ink-soft)">Баллы</span><span class="mono">{{ patient.loyalty_points }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0">
              <span style="color:var(--ink-soft)">Действует</span><span>по всей сети</span>
            </div>
          </div>
        </div>

        <div>
          <div style="display:flex;gap:6px;border-bottom:1px solid var(--line);margin-bottom:16px">
            <div
              v-for="tab in [
                { key: 'timeline', label: 'Лента визитов' },
                { key: 'referrals', label: 'Направления' },
                { key: 'labs', label: 'Анализы' },
                { key: 'documents', label: 'Документы' },
              ]"
              :key="tab.key"
              style="padding:10px 4px;font-size:13px;font-weight:600;cursor:pointer;margin-right:18px;border-bottom:2px solid transparent"
              :style="activeTab === tab.key ? 'color:var(--navy);border-color:var(--mint)' : 'color:var(--ink-soft)'"
              @click="activeTab = tab.key"
            >
              {{ tab.label }}
            </div>
          </div>

          <div v-if="activeTab === 'timeline'" class="panel">
            <p v-if="visitsError" class="text-sm text-red-600">{{ visitsError }}</p>
            <div
              v-for="item in timeline"
              :key="`${item.type}-${item.raw.id}`"
              style="display:flex;gap:14px;padding:14px 0;border-bottom:1px solid #F1EEE6"
            >
              <div
                class="mono"
                style="width:30px;height:30px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff"
                :style="{ background: item.type === 'visit' ? 'var(--mint)' : item.type === 'referral' ? 'var(--amber)' : 'var(--navy)' }"
              >
                {{ item.type === 'visit' ? 'В' : item.type === 'referral' ? 'Н' : 'Л' }}
              </div>
              <div style="flex:1">
                <template v-if="item.type === 'visit'">
                  <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="font-size:13.5px;font-weight:600">Приём — {{ item.raw.doctor_name }}</span>
                    <span class="mono" style="font-size:11px;color:var(--ink-soft)">{{ formatDateTime(item.raw.created_at) }}</span>
                  </div>
                  <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">{{ item.raw.branch_name }}</div>
                  <div v-if="item.raw.reason" style="font-size:12.5px;margin-top:6px;background:#FBFAF7;border:1px solid #F0EDE5;border-radius:8px;padding:8px 10px">{{ item.raw.reason }}</div>
                  <div style="margin-top:8px;display:flex;gap:6px">
                    <button class="chip" @click="openLabOrder(item.raw)">Заказать анализ</button>
                    <button class="chip" @click="openReferral(item.raw)">Направить →</button>
                  </div>
                </template>
                <template v-else-if="item.type === 'referral'">
                  <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="font-size:13.5px;font-weight:600">
                      Направление → {{ item.raw.to_doctor_name || `${item.raw.to_specialty_name} (на специальность)` }}
                    </span>
                    <span class="mono" style="font-size:11px;color:var(--ink-soft)">{{ formatDateTime(item.raw.created_at) }}</span>
                  </div>
                  <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">{{ item.raw.to_branch_name }}</div>
                </template>
                <template v-else>
                  <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="font-size:13.5px;font-weight:600">
                      Анализ — {{ item.raw.test_type }}
                      <span v-if="item.raw.result" class="pill" :class="item.raw.result.is_abnormal ? 'abnormal' : 'ok'" style="margin-left:6px">
                        {{ item.raw.result.is_abnormal ? 'Отклонение' : 'В норме' }}
                      </span>
                    </span>
                    <span class="mono" style="font-size:11px;color:var(--ink-soft)">{{ formatDateTime(item.raw.created_at) }}</span>
                  </div>
                  <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">{{ item.raw.branch_name }}</div>
                </template>
              </div>
            </div>
            <p v-if="timeline.length === 0" style="text-align:center;color:var(--ink-soft);padding:24px">Записей пока нет.</p>
          </div>

          <div v-else-if="activeTab === 'referrals'" class="panel">
            <p v-if="referralsError" class="text-sm text-red-600">{{ referralsError }}</p>
            <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
              <tbody>
                <tr v-for="r in referrals" :key="r.id" style="border-bottom:1px solid #F1EEE6">
                  <td style="padding:10px 4px">{{ r.to_doctor_name || `${r.to_specialty_name} (на специальность)` }}</td>
                  <td style="padding:10px 4px;color:var(--ink-soft)">{{ r.to_branch_name }}</td>
                  <td style="padding:10px 4px"><span class="pill ok">{{ r.status }}</span></td>
                  <td class="mono" style="padding:10px 4px;color:var(--ink-soft);text-align:right">{{ formatDateTime(r.created_at) }}</td>
                </tr>
                <tr v-if="referrals.length === 0"><td style="padding:16px;text-align:center;color:var(--ink-soft)">Направлений пока нет.</td></tr>
              </tbody>
            </table>
          </div>

          <div v-else-if="activeTab === 'labs'" class="panel">
            <LabOrdersSection ref="labOrdersSection" :patient-id="id" />
          </div>

          <div v-else class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
            Загрузка и хранение документов пациента пока не реализованы.
          </div>
        </div>
      </div>
    </template>

    <ReferralModal
      v-if="activeVisit"
      :open="modalOpen"
      :patient="patient"
      :visit="activeVisit"
      @close="modalOpen = false"
      @created="onCreated"
    />
    <LabOrderModal
      v-if="activeLabOrderVisit"
      :open="labOrderModalOpen"
      :patient="patient"
      :visit="activeLabOrderVisit"
      @close="labOrderModalOpen = false"
      @created="onLabOrderCreated"
    />
  </div>
</template>
