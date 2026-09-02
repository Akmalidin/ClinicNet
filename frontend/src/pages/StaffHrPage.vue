<script setup>
import { computed, onMounted, ref } from 'vue'

import { staffApi } from '../api'

const staff = ref([])
const loadError = ref('')
const activeFilter = ref('all')

async function load() {
  loadError.value = ''
  try {
    const { data } = await staffApi.list()
    staff.value = data
  } catch (e) {
    loadError.value = e.response?.status === 403
      ? 'Доступно только администратору сети.'
      : 'Не удалось загрузить список персонала.'
  }
}
onMounted(load)

const FILTERS = [
  { key: 'all', label: 'Все' },
  { key: 'doctor', label: 'Врачи' },
  { key: 'nurse', label: 'Медсёстры' },
  { key: 'license', label: 'Лицензии истекают' },
]

function matchesFilter(person) {
  if (activeFilter.value === 'all') return true
  if (activeFilter.value === 'license') return person.license_status === 'warning' || person.license_status === 'expired'
  const needle = activeFilter.value === 'doctor' ? 'Врач' : 'медсестра'
  return person.roles.some((r) => r.toLowerCase().includes(needle.toLowerCase()))
}
const filteredStaff = computed(() => staff.value.filter(matchesFilter))

function initials(name) {
  return name.split(' ').map((s) => s[0]).join('').slice(0, 2).toUpperCase()
}
const licenseNote = {
  ok: (d) => `Лицензия до ${d}`,
  warning: (d) => `Истекает ${d}`,
  expired: (d) => `Истекла ${d}`,
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div><h1>Персонал сети</h1><div class="meta">{{ staff.length }} сотрудников</div></div>
    </div>

    <div class="toolbar">
      <div v-for="f in FILTERS" :key="f.key" class="chip" :class="{ active: activeFilter === f.key }" @click="activeFilter = f.key">
        {{ f.label }}
      </div>
    </div>

    <div v-if="loadError" class="content"><p class="text-sm text-red-600">{{ loadError }}</p></div>

    <div v-else class="content">
      <div
        v-for="person in filteredStaff"
        :key="person.id"
        class="panel"
        style="padding:16px 20px;display:grid;grid-template-columns:auto 1.4fr 1fr 1fr auto;gap:18px;align-items:center"
      >
        <div style="display:flex;align-items:center;gap:12px">
          <div class="avatar">{{ initials(person.name) }}</div>
          <div>
            <div style="font-size:14px;font-weight:600">{{ person.name }}</div>
            <div style="font-size:11.5px;color:var(--ink-soft);margin-top:2px">{{ person.job_title || person.roles.join(', ') }}</div>
          </div>
        </div>
        <div style="display:flex;gap:5px;flex-wrap:wrap">
          <span v-for="b in person.branches" :key="b" class="pill ok">{{ b }}</span>
          <span v-if="person.branches.length === 0" style="font-size:11px;color:var(--ink-soft)">без филиала</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:3px">
          <span style="font-size:10px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:0.04em">Приёмов / нед</span>
          <span class="mono" style="font-size:15px;font-weight:600;color:var(--navy)">{{ person.appointments_last_7_days }}</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:3px">
          <span style="font-size:10px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:0.04em">Завершено (30 дн.)</span>
          <span class="mono" style="font-size:15px;font-weight:600;color:var(--navy)">
            {{ person.conversion_rate == null ? '—' : `${person.conversion_rate}%` }}
          </span>
        </div>
        <div v-if="person.license_expires_at" style="display:flex;align-items:center;gap:6px;font-size:11.5px" :style="{ color: person.license_status === 'ok' ? 'var(--mint-d)' : 'var(--amber)', fontWeight: person.license_status === 'ok' ? 400 : 600 }">
          <span style="width:6px;height:6px;border-radius:50%;background:currentColor"></span>
          {{ licenseNote[person.license_status](person.license_expires_at) }}
        </div>
        <div v-else></div>
      </div>

      <div v-if="filteredStaff.length === 0" class="panel" style="text-align:center;color:var(--ink-soft);padding:24px">
        Никого не найдено.
      </div>
    </div>
  </div>
</template>
