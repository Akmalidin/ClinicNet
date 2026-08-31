<script setup>
import { onMounted, ref } from 'vue'

import { labOrdersApi } from '../../api'

// Заказы анализов для одного пациента + ручной ввод результата. Патиент —
// сетевой (единая ЭМК), поэтому список тут ПО ПАЦИЕНТУ, а не по филиалу:
// показывает заказы из любого филиала, куда у текущего пользователя есть
// diagnostics.view (тот же принцип, что и раздел "Приёмы" на этой же
// странице — тут просто отфильтровано бэкендом через ?patient=).
const props = defineProps({ patientId: { type: [String, Number], required: true } })

const orders = ref([])
const loadError = ref('')

const resultRowId = ref(null)
const resultText = ref('')
const resultAbnormal = ref(false)
const resultError = ref('')
const submitting = ref(false)

const statusBadge = { ordered: 'badge-yellow', completed: 'badge-green', cancelled: 'badge-gray' }
const urgencyBadge = { routine: 'badge-gray', urgent: 'badge-yellow', emergency: 'badge-red' }
const urgencyLabel = { routine: 'Плановое', urgent: 'Срочное', emergency: 'Экстренное' }

async function load() {
  loadError.value = ''
  try {
    const { data } = await labOrdersApi.list({ patient: props.patientId })
    orders.value = data.results ?? data
  } catch {
    loadError.value = 'Не удалось загрузить заказы анализов.'
  }
}
defineExpose({ load })
onMounted(load)

function openResultForm(order) {
  resultRowId.value = order.id
  resultText.value = ''
  resultAbnormal.value = false
  resultError.value = ''
}
function closeResultForm() {
  resultRowId.value = null
}

async function submitResult(order) {
  if (!resultText.value.trim()) {
    resultError.value = 'Укажите результат.'
    return
  }
  resultError.value = ''
  submitting.value = true
  try {
    await labOrdersApi.addResult(order.id, {
      result_text: resultText.value.trim(),
      is_abnormal: resultAbnormal.value,
    })
    closeResultForm()
    await load()
  } catch (e) {
    resultError.value = e.response?.data?.detail || 'Не удалось сохранить результат.'
  } finally {
    submitting.value = false
  }
}

async function cancelOrder(order) {
  try {
    await labOrdersApi.cancel(order.id)
    await load()
  } catch {
    loadError.value = 'Не удалось отменить заказ.'
  }
}
</script>

<template>
  <section class="card p-4">
    <h2 class="text-sm font-medium text-gray-500 mb-3">Анализы</h2>
    <p v-if="loadError" class="text-sm text-red-600">{{ loadError }}</p>
    <ul v-else class="divide-y divide-gray-100">
      <li v-for="order in orders" :key="order.id" class="py-3">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-sm text-gray-900">
              {{ order.test_type }}
              <span :class="urgencyBadge[order.urgency] ?? 'badge-gray'" class="ml-1">
                {{ urgencyLabel[order.urgency] ?? order.urgency }}
              </span>
            </p>
            <p class="text-xs text-gray-500">
              {{ order.branch_name }} · {{ order.ordered_by_name }}
              <span :class="statusBadge[order.status] ?? 'badge-gray'" class="ml-1">{{ order.status }}</span>
            </p>
          </div>
          <div class="shrink-0 flex gap-1">
            <button
              v-if="order.status === 'ordered'"
              class="btn-secondary text-xs px-2 py-1"
              @click="openResultForm(order)"
            >
              Ввести результат
            </button>
            <button
              v-if="order.status === 'ordered'"
              class="btn-secondary text-xs px-2 py-1"
              @click="cancelOrder(order)"
            >
              Отменить
            </button>
          </div>
        </div>

        <div v-if="order.result" class="mt-2 text-sm rounded-md bg-gray-50 px-3 py-2">
          <span v-if="order.result.is_abnormal" class="badge-red mr-2">Вне нормы</span>
          <span v-else class="badge-green mr-2">В норме</span>
          {{ order.result.result_text }}
          <span class="text-xs text-gray-400">— {{ order.result.entered_by_name }}</span>
        </div>

        <div v-if="resultRowId === order.id" class="mt-2 space-y-2 bg-gray-50 rounded-md p-3">
          <textarea v-model="resultText" class="form-input" rows="2" placeholder="Результат" />
          <label class="flex items-center gap-2 text-sm text-gray-700">
            <input v-model="resultAbnormal" type="checkbox" />
            Результат вне нормы
          </label>
          <p v-if="resultError" class="text-sm text-red-600">{{ resultError }}</p>
          <div class="flex gap-2">
            <button class="btn-primary text-sm" :disabled="submitting" @click="submitResult(order)">
              Сохранить
            </button>
            <button class="btn-secondary text-sm" @click="closeResultForm">Отмена</button>
          </div>
        </div>
      </li>
      <li v-if="orders.length === 0" class="py-3 text-sm text-gray-400">Анализы не заказывались.</li>
    </ul>
  </section>
</template>
