<script setup>
import { ref, watch } from 'vue'

import { labOrdersApi } from '../../api'

// Заказ анализа из карты пациента (ClinicNet-Phase2-Frontend-Prompt.md,
// "базовая диагностика") — deliberately simple: test_type is free text
// (no test catalog, matching the same choice already made for
// Visit.reason/Referral.reason), comment, urgency. No result entry here —
// that's a separate step, done later by "ответственный сотрудник" (see
// LabOrdersSection.vue), possibly a different person than who orders it.
const props = defineProps({
  open: { type: Boolean, required: true },
  patient: { type: Object, required: true },
  // The visit this order is placed from — supplies branch + source_visit.
  visit: { type: Object, required: true },
})
const emit = defineEmits(['close', 'created'])

const testType = ref('')
const comment = ref('')
const urgency = ref('routine')
const submitting = ref(false)
const submitError = ref('')

function reset() {
  testType.value = ''
  comment.value = ''
  urgency.value = 'routine'
  submitError.value = ''
}
watch(() => props.open, (isOpen) => { if (isOpen) reset() })

async function submit() {
  submitError.value = ''
  submitting.value = true
  try {
    const { data } = await labOrdersApi.create({
      patient: props.patient.id,
      branch: props.visit.branch,
      source_visit: props.visit.id,
      test_type: testType.value.trim(),
      comment: comment.value,
      urgency: urgency.value,
    })
    emit('created', data)
    emit('close')
  } catch (e) {
    const data = e.response?.data
    submitError.value =
      (data && (data.detail || Object.values(data).flat().join(' '))) ||
      'Не удалось заказать анализ.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 bg-black/30 flex items-center justify-center z-40 p-4"
    @click.self="emit('close')"
  >
    <div class="card w-full max-w-md p-6 space-y-4">
      <header class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-gray-900">
          Заказать анализ · {{ patient.first_name }} {{ patient.last_name }}
        </h2>
        <button class="text-gray-400 hover:text-gray-600" @click="emit('close')">✕</button>
      </header>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Тип анализа</label>
        <input v-model="testType" class="form-input" required maxlength="200" placeholder="Общий анализ крови" />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Комментарий</label>
        <textarea v-model="comment" class="form-input" rows="2" />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Срочность</label>
        <select v-model="urgency" class="form-input">
          <option value="routine">Плановое</option>
          <option value="urgent">Срочное</option>
          <option value="emergency">Экстренное</option>
        </select>
      </div>

      <p v-if="submitError" class="text-sm text-red-600">{{ submitError }}</p>

      <div class="flex justify-end gap-2 pt-2">
        <button class="btn-secondary" :disabled="submitting" @click="emit('close')">Отмена</button>
        <button class="btn-primary" :disabled="submitting || !testType.trim()" @click="submit">
          {{ submitting ? 'Заказываем…' : 'Заказать' }}
        </button>
      </div>
    </div>
  </div>
</template>
