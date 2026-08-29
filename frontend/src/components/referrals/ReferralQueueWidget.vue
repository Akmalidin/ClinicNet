<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { appointmentsApi, referralsApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

// Reusable for both a branch dashboard (pass `branch`) and the network
// dashboard (omit it) — spec step 7.
//
// IMPORTANT — client-side branch guard: this widget does NOT trust that
// GET /referrals/ already filtered rows correctly. It re-checks every row
// itself against auth.referralBranches (fetched independently via /me/,
// computed server-side by the same rbac.branches_for_permission()
// ReferralViewSet's own get_queryset uses — see MeView's docstring) plus
// the same "own" bypass the backend applies (from_doctor/to_doctor === me).
// A row that fails this re-check is dropped and reported via
// console.error rather than rendered — if the backend ever regresses (as
// actually happened once already this project: see
// apps/referrals/permissions.py's docstring on the referrals.view leak
// this session's predecessor found and fixed), this widget silently
// hides the leak instead of displaying another branch's queue.
const props = defineProps({
  branch: { type: [String, Number], default: null },
})

const auth = useAuthStore()

const referrals = ref([])
const loadError = ref('')
const droppedCount = ref(0)

const actionRowId = ref(null) // which row has its action panel open
const actionKind = ref(null) // 'decline' | 'schedule' | 'complete'
const actionError = ref('')
const actionSubmitting = ref(false)
const outcomeNote = ref('')
const slotsByDate = ref({})
const slotsLoading = ref(false)

function isVisible(referral) {
  const own = referral.from_doctor === auth.user?.id || referral.to_doctor === auth.user?.id
  if (own) return true
  const branchOk =
    auth.referralBranches.includes(referral.from_branch) ||
    auth.referralBranches.includes(referral.to_branch)
  if (!branchOk) return false
  // If a specific branch was requested, the row also has to actually
  // belong to it — don't trust the ?branch= filter's own correctness either.
  if (props.branch != null) {
    return referral.from_branch === Number(props.branch) || referral.to_branch === Number(props.branch)
  }
  return true
}

async function load() {
  loadError.value = ''
  try {
    const { data } = await referralsApi.list(props.branch != null ? { branch: props.branch } : {})
    const rows = data.results ?? data
    const visible = rows.filter(isVisible)
    droppedCount.value = rows.length - visible.length
    if (droppedCount.value > 0) {
      // eslint-disable-next-line no-console
      console.error(
        `ReferralQueueWidget: dropped ${droppedCount.value} row(s) that failed the client-side ` +
          'branch guard — the backend returned referrals outside what /me/ says this user can see.',
      )
    }
    referrals.value = visible
  } catch {
    loadError.value = 'Не удалось загрузить очередь направлений.'
  }
}
onMounted(load)
watch(() => props.branch, load)

function closeAction() {
  actionRowId.value = null
  actionKind.value = null
  actionError.value = ''
  outcomeNote.value = ''
  slotsByDate.value = {}
}

function openAction(referral, kind) {
  actionRowId.value = referral.id
  actionKind.value = kind
  actionError.value = ''
  outcomeNote.value = ''
  slotsByDate.value = {}
  if (kind === 'schedule') loadSlots(referral)
}

function nextThreeDates() {
  const dates = []
  const today = new Date()
  for (let i = 0; i < 3; i += 1) {
    const d = new Date(today)
    d.setDate(d.getDate() + i)
    dates.push(d.toISOString().slice(0, 10))
  }
  return dates
}

async function loadSlots(referral) {
  slotsLoading.value = true
  try {
    const dates = nextThreeDates()
    const results = await Promise.all(
      dates.map((date) => referralsApi.availableSlots(referral.to_doctor, date)),
    )
    const byDate = {}
    dates.forEach((date, i) => {
      byDate[date] = results[i].data
    })
    slotsByDate.value = byDate
  } finally {
    slotsLoading.value = false
  }
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

async function bookSlot(referral, slot) {
  actionError.value = ''
  actionSubmitting.value = true
  try {
    const { data: appointment } = await appointmentsApi.create({
      branch: referral.to_branch,
      patient: referral.patient,
      doctor: referral.to_doctor,
      starts_at: slot.starts_at,
      ends_at: slot.ends_at,
    })
    await referralsApi.schedule(referral.id, appointment.id)
    closeAction()
    await load()
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось забронировать слот.'
  } finally {
    actionSubmitting.value = false
  }
}

async function submitDecline(referral) {
  if (!outcomeNote.value.trim()) {
    actionError.value = 'Укажите причину отказа.'
    return
  }
  actionError.value = ''
  actionSubmitting.value = true
  try {
    await referralsApi.decline(referral.id, outcomeNote.value.trim())
    closeAction()
    await load()
  } catch (e) {
    actionError.value = e.response?.data?.outcome_note || e.response?.data?.detail || 'Не удалось отклонить.'
  } finally {
    actionSubmitting.value = false
  }
}

async function submitComplete(referral) {
  actionError.value = ''
  actionSubmitting.value = true
  try {
    await referralsApi.complete(referral.id, outcomeNote.value.trim())
    closeAction()
    await load()
  } catch (e) {
    actionError.value = e.response?.data?.detail || 'Не удалось завершить направление.'
  } finally {
    actionSubmitting.value = false
  }
}

const statusBadge = {
  pending: 'badge-yellow',
  scheduled: 'badge-blue',
  accepted: 'badge-blue',
  completed: 'badge-green',
  declined: 'badge-red',
  cancelled: 'badge-gray',
}
const priorityBadge = {
  routine: 'badge-gray',
  urgent: 'badge-yellow',
  emergency: 'badge-red',
}
const priorityLabel = { routine: 'Плановое', urgent: 'Срочное', emergency: 'Экстренное' }

function targetLabel(referral) {
  return referral.to_doctor_name || `${referral.to_specialty_name} (на специальность)`
}

const openReferrals = computed(() => referrals.value.filter((r) => !['completed', 'declined', 'cancelled'].includes(r.status)))
</script>

<template>
  <div class="card">
    <div v-if="loadError" class="p-4 text-sm text-red-600">{{ loadError }}</div>
    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="border-b border-gray-100 text-left text-gray-500">
          <tr>
            <th class="px-4 py-2 font-medium">Пациент</th>
            <th class="px-4 py-2 font-medium">От кого</th>
            <th class="px-4 py-2 font-medium">Кому / куда</th>
            <th class="px-4 py-2 font-medium">Причина</th>
            <th class="px-4 py-2 font-medium">Статус</th>
            <th class="px-4 py-2 font-medium">Приоритет</th>
            <th class="px-4 py-2 font-medium">Действия</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <template v-for="referral in openReferrals" :key="referral.id">
            <tr>
              <td class="px-4 py-2">{{ referral.patient_name }}</td>
              <td class="px-4 py-2 text-gray-500">{{ referral.from_doctor_name }} · {{ referral.from_branch_name }}</td>
              <td class="px-4 py-2">
                {{ targetLabel(referral) }} · {{ referral.to_branch_name }}
                <span v-if="referral.is_cross_branch" class="badge-blue ml-1">между филиалами</span>
              </td>
              <td class="px-4 py-2 text-gray-500">{{ referral.reason }}</td>
              <td class="px-4 py-2">
                <span :class="statusBadge[referral.status] ?? 'badge-gray'">{{ referral.status }}</span>
              </td>
              <td class="px-4 py-2">
                <span :class="priorityBadge[referral.priority] ?? 'badge-gray'">
                  {{ priorityLabel[referral.priority] ?? referral.priority }}
                </span>
              </td>
              <td class="px-4 py-2 whitespace-nowrap">
                <button
                  v-if="referral.to_doctor && referral.status === 'pending'"
                  class="btn-secondary text-xs px-2 py-1 mr-1"
                  @click="openAction(referral, 'schedule')"
                >
                  Забронировать
                </button>
                <button
                  v-if="!['declined', 'completed'].includes(referral.status)"
                  class="btn-secondary text-xs px-2 py-1 mr-1"
                  @click="openAction(referral, 'decline')"
                >
                  Отклонить
                </button>
                <button
                  v-if="['scheduled', 'accepted'].includes(referral.status)"
                  class="btn-secondary text-xs px-2 py-1"
                  @click="openAction(referral, 'complete')"
                >
                  Завершить
                </button>
              </td>
            </tr>

            <tr v-if="actionRowId === referral.id" class="bg-gray-50">
              <td colspan="7" class="px-4 py-3">
                <div v-if="actionKind === 'schedule'" class="space-y-2">
                  <p class="text-xs font-medium text-gray-500">
                    Свободные окна {{ referral.to_doctor_name }} на ближайшие 3 дня
                  </p>
                  <p v-if="slotsLoading" class="text-sm text-gray-400">Загружаем слоты…</p>
                  <div v-else class="space-y-1">
                    <div v-for="(slots, date) in slotsByDate" :key="date">
                      <template v-if="slots.length">
                        <span class="text-xs text-gray-500 mr-2">{{ date }}</span>
                        <button
                          v-for="slot in slots"
                          :key="slot.starts_at"
                          class="badge-gray hover:bg-primary hover:text-white transition-colors mr-1 mb-1"
                          :disabled="actionSubmitting"
                          @click="bookSlot(referral, slot)"
                        >
                          {{ formatTime(slot.starts_at) }}–{{ formatTime(slot.ends_at) }}
                        </button>
                      </template>
                    </div>
                  </div>
                </div>

                <div v-else-if="actionKind === 'decline'" class="flex items-end gap-2">
                  <div class="flex-1">
                    <label class="block text-xs font-medium text-gray-500 mb-1">Причина отказа</label>
                    <input v-model="outcomeNote" class="form-input" />
                  </div>
                  <button class="btn-primary text-sm" :disabled="actionSubmitting" @click="submitDecline(referral)">
                    Отклонить
                  </button>
                  <button class="btn-secondary text-sm" @click="closeAction">Отмена</button>
                </div>

                <div v-else-if="actionKind === 'complete'" class="flex items-end gap-2">
                  <div class="flex-1">
                    <label class="block text-xs font-medium text-gray-500 mb-1">
                      Комментарий по итогу (необязательно)
                    </label>
                    <input v-model="outcomeNote" class="form-input" />
                  </div>
                  <button class="btn-primary text-sm" :disabled="actionSubmitting" @click="submitComplete(referral)">
                    Завершить
                  </button>
                  <button class="btn-secondary text-sm" @click="closeAction">Отмена</button>
                </div>

                <p v-if="actionError" class="text-sm text-red-600 mt-2">{{ actionError }}</p>
              </td>
            </tr>
          </template>

          <tr v-if="openReferrals.length === 0">
            <td colspan="7" class="px-4 py-6 text-center text-gray-400">Открытых направлений нет.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
