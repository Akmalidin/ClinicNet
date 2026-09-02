<script setup>
import { computed, onMounted, ref } from 'vue'

import { rolesApi } from '../api'

// No dedicated "who can see this page" permission exists in the backend
// (RoleViewSet/PermissionViewSet are IsAuthenticated-only, see their
// docstrings — informational structure, not per-tenant secrets). This
// gate is cosmetic, matching that same posture, not a real security
// boundary: an actual RBAC check would need a backend permission code
// that doesn't exist yet (out of scope for porting this screen).
const roles = ref([])
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    const { data } = await rolesApi.list()
    roles.value = data.results ?? data
  } catch {
    loadError.value = 'Не удалось загрузить роли и права.'
  }
}
onMounted(load)

const CATEGORY_LABELS = {
  branches: 'Филиалы и графики',
  patients: 'Пациенты',
  scheduling: 'Расписание',
  visits: 'Приёмы (ЭМК)',
  referrals: 'Направления',
  diagnostics: 'Анализы',
  finance: 'Финансы',
  inventory: 'Склад',
  inpatient: 'Стационар',
  churn: 'Отток пациентов',
  triage: 'AI-триаж',
}
const ROLE_ORDER = [
  'network-admin', 'branch-admin', 'department-head', 'doctor',
  'nurse', 'receptionist', 'cashier', 'triage-bot',
]

const orderedRoles = computed(() =>
  [...roles.value].sort((a, b) => {
    const ai = ROLE_ORDER.indexOf(a.codename)
    const bi = ROLE_ORDER.indexOf(b.codename)
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi)
  }),
)

// The permission catalog isn't fetched separately — network-admin holds
// every permission that exists (seed_rbac.py: ROLES['network-admin'] =
// every code in PERMISSIONS), so the union of all roles' permissions
// already equals the full catalog. One request instead of two.
const groupedPermissions = computed(() => {
  const byCode = new Map()
  for (const role of roles.value) {
    for (const perm of role.permissions) byCode.set(perm.code, perm)
  }
  const byCategory = new Map()
  for (const perm of byCode.values()) {
    if (!byCategory.has(perm.category)) byCategory.set(perm.category, [])
    byCategory.get(perm.category).push(perm)
  }
  for (const list of byCategory.values()) list.sort((a, b) => a.code.localeCompare(b.code))
  return [...byCategory.entries()]
    .sort(([a], [b]) => (CATEGORY_LABELS[a] ?? a).localeCompare(CATEGORY_LABELS[b] ?? b))
    .map(([category, perms]) => ({ category, label: CATEGORY_LABELS[category] ?? category, perms }))
})

function grantFor(role, code) {
  return role.permissions.some((p) => p.code === code)
}

// Branch/department vs. network-wide scoping is a per-UserRole property
// in this backend (BranchScope on the actual grant), not a static
// property of a Role — RolePermission carries no scope. The mockup's
// amber "B" marker is reproduced here from the one real, documented
// convention in seed_rbac.py: every role except network-admin is
// provisioned branch- or department-scoped, network-admin is always
// ALL-scope ("видит всё"). This is that codebase convention rendered,
// not a live per-user check — an individual UserRole could in principle
// be granted differently.
function isNetworkWide(role) {
  return role.codename === 'network-admin'
}
</script>

<template>
  <div class="mockup-page">
    <div class="topbar">
      <div><h1>Роли и доступ</h1><div class="meta">Матрица прав · зелёный = разрешено · жёлтый B = только свой филиал/отделение</div></div>
    </div>

    <div v-if="loadError" class="content"><p class="text-sm text-red-600">{{ loadError }}</p></div>

    <div v-else class="content">
      <div class="panel" style="overflow-x:auto;padding:0">
        <table style="width:100%;border-collapse:collapse;font-size:12.5px">
          <thead>
            <tr>
              <th style="background:#FBFAF7;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;color:var(--ink-soft);padding:12px 10px;border-bottom:1px solid var(--line);border-right:1px solid #F0EDE5;text-align:left;min-width:260px">
                Право
              </th>
              <th
                v-for="role in orderedRoles"
                :key="role.id"
                style="background:#FBFAF7;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;color:var(--navy);font-weight:700;padding:12px 10px;border-bottom:1px solid var(--line);border-right:1px solid #F0EDE5;text-align:center"
              >
                {{ role.name }}
                <span v-if="isNetworkWide(role)" style="display:block;font-size:10px;font-weight:400;text-transform:none;color:var(--ink-soft);margin-top:2px">видит всё</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-for="group in groupedPermissions" :key="group.category">
              <tr>
                <td :colspan="orderedRoles.length + 1" style="background:#FBFAF7;font-weight:700;font-size:11.5px;text-transform:uppercase;letter-spacing:0.04em;color:var(--navy);padding:9px 10px">
                  {{ group.label }}
                </td>
              </tr>
              <tr v-for="perm in group.perms" :key="perm.code">
                <td style="padding:11px 10px;border-bottom:1px solid #F1EEE6;border-right:1px solid #F5F3EC;font-weight:500" :title="perm.description">
                  {{ perm.code }}
                </td>
                <td
                  v-for="role in orderedRoles"
                  :key="role.id"
                  style="padding:11px 10px;border-bottom:1px solid #F1EEE6;border-right:1px solid #F5F3EC;text-align:center"
                >
                  <span
                    v-if="grantFor(role, perm.code)"
                    class="mono"
                    :style="isNetworkWide(role)
                      ? 'width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;background:var(--mint-l);color:var(--mint-d)'
                      : 'width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;background:var(--amber);color:#3B2E14'"
                  >{{ isNetworkWide(role) ? '✓' : 'B' }}</span>
                  <span v-else style="width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;background:#F1EEE6;color:transparent">·</span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
