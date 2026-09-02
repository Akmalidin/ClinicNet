<script setup>
import { computed, onMounted, ref } from 'vue'

import { invoicesApi, patientsApi } from '../api'

const props = defineProps({ id: { type: [String, Number], required: true } })

const invoice = ref(null)
const patient = ref(null)
const loadError = ref('')
const payError = ref('')
const paySubmitting = ref(false)
const method = ref('cash')
const amount = ref('')

const METHODS = [
  { key: 'cash', label: 'Наличные' },
  { key: 'card', label: 'Карта' },
  { key: 'qr', label: 'QR / Мобильный' },
  { key: 'bonus', label: 'Бонусами' },
]

async function load() {
  loadError.value = ''
  try {
    const { data } = await invoicesApi.get(props.id)
    invoice.value = data
    amount.value = data.balance_due
    const { data: patientData } = await patientsApi.get(data.patient)
    patient.value = patientData
  } catch {
    loadError.value = 'Не удалось загрузить счёт.'
  }
}
onMounted(load)

const insuranceShare = computed(() => {
  if (!invoice.value || !invoice.value.insurance_policy) return null
  const total = Number(invoice.value.total_amount)
  const covered = Number(invoice.value.insurance_covered_amount)
  return { covered, patientShare: total - covered, coveredPct: total > 0 ? (covered / total) * 100 : 0 }
})

function formatMoney(v) {
  return `${Number(v).toLocaleString('ru-RU')} ⃀`
}
function formatDateTime(iso) {
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function selectMethod(m) {
  method.value = m
  payError.value = ''
}

async function submitPayment() {
  payError.value = ''
  const value = Number(amount.value)
  if (!value || value <= 0) {
    payError.value = 'Укажите сумму больше нуля.'
    return
  }
  if (method.value === 'bonus' && value > (patient.value?.loyalty_points ?? 0)) {
    payError.value = `На счету пациента только ${patient.value.loyalty_points} баллов.`
    return
  }
  paySubmitting.value = true
  try {
    const { data } = await invoicesApi.pay(props.id, { kind: 'payment', amount: value, method: method.value })
    invoice.value = data
    const { data: patientData } = await patientsApi.get(data.patient)
    patient.value = patientData
    amount.value = data.balance_due
  } catch (e) {
    payError.value = e.response?.data?.detail || 'Не удалось провести оплату.'
  } finally {
    paySubmitting.value = false
  }
}
</script>

<template>
  <div class="mockup-page">
    <div v-if="loadError" class="p-6 text-sm text-red-600">{{ loadError }}</div>

    <template v-else-if="invoice && patient">
      <div class="topbar">
        <div>
          <h1>Касса — счёт №CN-{{ String(invoice.id).padStart(5, '0') }}</h1>
          <div class="meta">{{ invoice.patient_name }} · {{ invoice.branch_name }} · {{ formatDateTime(invoice.created_at) }}</div>
        </div>
        <span class="badge-blue" style="font-size:11px;background:var(--mint-l);color:var(--mint-d);padding:4px 10px;border-radius:999px;font-weight:600">
          {{ invoice.branch_name }}
        </span>
      </div>

      <div style="padding:26px 32px;display:grid;grid-template-columns:1fr 380px;gap:22px">
        <div class="panel">
          <h3 style="margin-bottom:16px">Позиции чека</h3>
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr>
                <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 8px 10px;border-bottom:1px solid var(--line)">Услуга</th>
                <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 8px 10px;border-bottom:1px solid var(--line);width:60px">Кол-во</th>
                <th class="mono" style="text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 8px 10px;border-bottom:1px solid var(--line)">Цена</th>
                <th class="mono" style="text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 8px 10px;border-bottom:1px solid var(--line)">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in invoice.lines" :key="line.id">
                <td style="padding:12px 8px;border-bottom:1px solid #F1EEE6;font-size:13px">{{ line.description }}</td>
                <td class="mono" style="padding:12px 8px;border-bottom:1px solid #F1EEE6;font-size:13px">{{ line.quantity }}</td>
                <td class="mono" style="text-align:right;padding:12px 8px;border-bottom:1px solid #F1EEE6;font-size:13px">{{ formatMoney(line.unit_price) }}</td>
                <td class="mono" style="text-align:right;padding:12px 8px;border-bottom:1px solid #F1EEE6;font-size:13px">{{ formatMoney(line.line_total) }}</td>
              </tr>
            </tbody>
          </table>

          <template v-if="insuranceShare">
            <h3 style="margin-top:24px">Разделение оплаты</h3>
            <div style="display:flex;height:12px;border-radius:999px;overflow:hidden;margin:14px 0">
              <div :style="{ background: 'var(--mint)', width: insuranceShare.coveredPct + '%' }"></div>
              <div :style="{ background: 'var(--amber)', width: (100 - insuranceShare.coveredPct) + '%' }"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--ink-soft)">
              <span>● Страховая ({{ invoice.insurance_provider_name }}) — {{ formatMoney(insuranceShare.covered) }}</span>
              <span>● Пациент — {{ formatMoney(insuranceShare.patientShare) }}</span>
            </div>
          </template>
        </div>

        <div class="panel">
          <h3>Итог</h3>
          <div style="display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #F1EEE6;font-size:13px">
            <span>Сумма позиций</span><span class="mono">{{ formatMoney(invoice.total_amount) }}</span>
          </div>
          <div v-if="insuranceShare" style="display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #F1EEE6;font-size:13px">
            <span>Покрытие ДМС</span><span class="mono" style="color:var(--mint-d)">− {{ formatMoney(invoice.insurance_covered_amount) }}</span>
          </div>
          <div style="display:flex;justify-content:space-between;font-weight:700;font-size:16px;padding-top:14px">
            <span>К оплате пациентом</span><span class="mono">{{ formatMoney(invoice.patient_owed_amount) }}</span>
          </div>

          <template v-if="!invoice.is_paid && invoice.status === 'issued'">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:16px">
              <div
                v-for="m in METHODS"
                :key="m.key"
                class="btn"
                :class="method === m.key ? 'btn-mint' : 'btn-outline'"
                style="text-align:center"
                @click="selectMethod(m.key)"
              >
                {{ m.label }}<template v-if="m.key === 'bonus'"> ({{ patient.loyalty_points }})</template>
              </div>
            </div>

            <input v-model="amount" type="number" step="0.01" class="form-input" style="margin-top:12px" />

            <button class="btn-complete" style="background:var(--mint)" :disabled="paySubmitting" @click="submitPayment">
              Провести оплату — {{ formatMoney(amount || 0) }}
            </button>
            <p v-if="payError" class="text-sm" style="color:var(--red);margin-top:8px">{{ payError }}</p>
          </template>
          <p v-else-if="invoice.is_paid" class="text-sm" style="color:var(--mint-d);margin-top:16px;font-weight:600">Счёт полностью оплачен.</p>
          <p v-else class="text-sm" style="color:var(--ink-soft);margin-top:16px">Счёт ещё не выставлен (черновик) — оплата недоступна.</p>
        </div>
      </div>
    </template>
  </div>
</template>
