<script setup>
import { computed, onMounted, ref } from 'vue'

import { branchesApi, stocksApi } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const stocks = ref([])
const branches = ref([])
const loadError = ref('')
const activeBranch = ref(null) // null = все филиалы
const onlyBelowMinimum = ref(false)

const restockRowId = ref(null)
const restockQty = ref('')
const restockError = ref('')
const restockSubmitting = ref(false)

function isVisible(stock) {
  return auth.inventoryBranches.includes(stock.branch)
}

async function load() {
  loadError.value = ''
  try {
    const [stocksRes, branchesRes] = await Promise.all([stocksApi.list(), branchesApi.directory()])
    const rows = stocksRes.data.results ?? stocksRes.data
    stocks.value = rows.filter(isVisible)
    branches.value = branchesRes.data
  } catch {
    loadError.value = 'Не удалось загрузить складские остатки.'
  }
}
onMounted(load)

const filteredStocks = computed(() =>
  stocks.value.filter((s) => {
    if (activeBranch.value != null && s.branch !== activeBranch.value) return false
    if (onlyBelowMinimum.value && !s.is_below_minimum) return false
    return true
  }),
)

const criticalAlerts = computed(() =>
  stocks.value.filter((s) => s.is_below_minimum).sort((a, b) => a.on_hand_quantity / a.min_quantity - b.on_hand_quantity / b.min_quantity),
)

function tier(stock) {
  if (!stock.is_below_minimum) return { label: 'В норме', cls: 'ok', color: 'var(--mint)' }
  const ratio = stock.min_quantity > 0 ? stock.on_hand_quantity / stock.min_quantity : 0
  return ratio < 0.5 ? { label: 'Критично', cls: 'crit', color: 'var(--red)' } : { label: 'Низкий', cls: 'low', color: 'var(--amber)' }
}
function fillWidth(stock) {
  if (stock.min_quantity <= 0) return '100%'
  return `${Math.min(100, Math.round((stock.on_hand_quantity / (stock.min_quantity * 2)) * 100))}%`
}

function openRestock(stock) {
  restockRowId.value = stock.id
  restockQty.value = ''
  restockError.value = ''
}
function closeRestock() {
  restockRowId.value = null
}
async function submitRestock(stock) {
  const qty = Number(restockQty.value)
  if (!qty || qty <= 0) {
    restockError.value = 'Укажите положительное количество.'
    return
  }
  restockError.value = ''
  restockSubmitting.value = true
  try {
    await stocksApi.adjust(stock.id, { quantity_delta: qty, reason: 'restock', note: 'Оприходование через веб' })
    closeRestock()
    await load()
  } catch (e) {
    restockError.value = e.response?.data?.detail || 'Не удалось оприходовать поставку.'
  } finally {
    restockSubmitting.value = false
  }
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div><h1>Складской учёт</h1><div class="meta">{{ branches.length }} филиалов · {{ stocks.length }} позиций</div></div>
    </div>

    <div class="toolbar">
      <div class="chip" :class="{ active: activeBranch == null }" @click="activeBranch = null">Все филиалы</div>
      <div
        v-for="branch in branches"
        :key="branch.id"
        class="chip"
        :class="{ active: activeBranch === branch.id }"
        @click="activeBranch = branch.id"
      >
        {{ branch.name }}
      </div>
      <div class="chip" style="margin-left:auto" :class="{ active: onlyBelowMinimum }" @click="onlyBelowMinimum = !onlyBelowMinimum">
        Ниже минимума
      </div>
    </div>

    <div v-if="loadError" class="content"><p class="text-sm text-red-600">{{ loadError }}</p></div>

    <div v-else class="content">
      <div v-if="criticalAlerts.length" style="display:flex;gap:12px;overflow-x:auto">
        <div
          v-for="stock in criticalAlerts"
          :key="stock.id"
          class="panel"
          :style="`flex-shrink:0;min-width:220px;padding:12px 16px;background:${tier(stock).cls === 'crit' ? 'var(--red-l)' : 'var(--amber-l)'};border-color:transparent`"
        >
          <div style="font-size:12.5px;font-weight:700" :style="{ color: tier(stock).color }">{{ stock.product_name }} ({{ stock.branch_name }})</div>
          <div style="font-size:11px;color:var(--ink-soft);margin-top:3px">
            Остаток {{ stock.on_hand_quantity }} {{ stock.product_unit }} · минимум {{ stock.min_quantity }} {{ stock.product_unit }}
          </div>
        </div>
      </div>

      <div class="panel" style="padding:22px">
        <table style="width:100%;border-collapse:collapse">
          <thead>
            <tr>
              <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)">Позиция</th>
              <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)">Филиал</th>
              <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)">Остаток</th>
              <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)">Мин. остаток</th>
              <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--ink-soft);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)">Статус</th>
              <th style="border-bottom:1px solid var(--line)"></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="stock in filteredStocks" :key="stock.id">
              <tr>
                <td style="padding:12px 10px;border-bottom:1px solid #F1EEE6;font-size:13px">{{ stock.product_name }}</td>
                <td style="padding:12px 10px;border-bottom:1px solid #F1EEE6;font-size:11.5px;color:var(--ink-soft)">{{ stock.branch_name }}</td>
                <td style="padding:12px 10px;border-bottom:1px solid #F1EEE6">
                  <span style="width:90px;height:7px;background:#EFECE3;border-radius:999px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:8px">
                    <span :style="{ display: 'block', height: '100%', borderRadius: '999px', width: fillWidth(stock), background: tier(stock).color }"></span>
                  </span>
                  <span class="mono">{{ stock.on_hand_quantity }} {{ stock.product_unit }}</span>
                </td>
                <td class="mono" style="padding:12px 10px;border-bottom:1px solid #F1EEE6;font-size:13px">{{ stock.min_quantity }} {{ stock.product_unit }}</td>
                <td style="padding:12px 10px;border-bottom:1px solid #F1EEE6">
                  <span class="pill" :class="tier(stock).cls">{{ tier(stock).label }}</span>
                </td>
                <td style="padding:12px 10px;border-bottom:1px solid #F1EEE6">
                  <button v-if="stock.is_below_minimum" class="chip" @click="openRestock(stock)">Оприходовать</button>
                </td>
              </tr>
              <tr v-if="restockRowId === stock.id">
                <td colspan="6" style="padding:0 10px 14px">
                  <div style="display:flex;align-items:center;gap:8px">
                    <input v-model="restockQty" type="number" min="0" class="form-input" style="max-width:140px" :placeholder="`Кол-во, ${stock.product_unit}`" />
                    <button class="btn btn-mint" :disabled="restockSubmitting" @click="submitRestock(stock)">Записать поступление</button>
                    <button class="btn btn-outline" @click="closeRestock">Отмена</button>
                  </div>
                  <p v-if="restockError" class="text-sm" style="color:var(--red);margin-top:6px">{{ restockError }}</p>
                </td>
              </tr>
            </template>
            <tr v-if="filteredStocks.length === 0">
              <td colspan="6" style="text-align:center;color:var(--ink-soft);padding:24px">Позиций не найдено.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
