import { defineStore } from 'pinia'

import { authApi, meApi } from '../api'
import { clearTokens, getTokens, setTokens } from '../api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    // roles: [{ role, branch_scope, branches }] — from MeView, informational.
    roles: [],
    // referral_branches: [id, ...] — branch ids where this user holds
    // referrals.view/manage, computed server-side by the same
    // rbac.branches_for_permission() ReferralViewSet itself uses (see
    // MeView's docstring). This is what ReferralQueueWidget.vue's
    // client-side branch guard re-checks each row against: an
    // independent fetch, never a trust of whatever the referrals list
    // endpoint already returned.
    referralBranches: [],
    // triage_branches: [id, ...] — same convention as referralBranches,
    // computed server-side by rbac.branches_for_permission() over
    // triage.view/triage.manage (see MeView). TriageQueueWidget.vue's
    // client-side branch guard re-checks each row against this, and
    // DashboardPage.vue uses it to decide whether to render the widget
    // at all — a user without triage.view shouldn't even fetch the
    // triage-suggestions endpoint (it'd just 403).
    triageBranches: [],
    // churn_branches: [id, ...] — same convention (ChurnAlertsPage.vue).
    churnBranches: [],
    // inventory_branches: [id, ...] — same convention (WarehouseStockPage.vue).
    inventoryBranches: [],
    // admission_departments: [id, ...] — one level deeper than the
    // *_branches lists above: DEPARTMENT ids, not branches (see
    // apps.inpatient.rbac's docstring). AdmissionIntakePage.vue's entry
    // point and client-side guard.
    admissionDepartments: [],
    ready: false,
  }),
  getters: {
    isAuthenticated: (state) => !!state.user,
  },
  actions: {
    async login(username, password) {
      const { data } = await authApi.login(username, password)
      setTokens({ access: data.access, refresh: data.refresh })
      await this.fetchMe()
    },
    logout() {
      clearTokens()
      this.user = null
      this.roles = []
      this.referralBranches = []
      this.triageBranches = []
      this.churnBranches = []
      this.inventoryBranches = []
      this.admissionDepartments = []
    },
    async fetchMe() {
      const { data } = await meApi.get()
      this.user = data
      this.roles = data.roles ?? []
      this.referralBranches = data.referral_branches ?? []
      this.triageBranches = data.triage_branches ?? []
      this.churnBranches = data.churn_branches ?? []
      this.inventoryBranches = data.inventory_branches ?? []
      this.admissionDepartments = data.admission_departments ?? []
    },
    // Called once on app boot: a stored access token doesn't mean it's
    // still valid, so this round-trips through /me/ (the request
    // interceptor in api/client.js will transparently refresh it if it's
    // merely expired) rather than trusting localStorage at face value.
    async restore() {
      const { access } = getTokens()
      if (access) {
        try {
          await this.fetchMe()
        } catch {
          clearTokens()
        }
      }
      this.ready = true
    },
  },
})
