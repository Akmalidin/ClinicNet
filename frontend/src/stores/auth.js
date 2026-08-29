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
    },
    async fetchMe() {
      const { data } = await meApi.get()
      this.user = data
      this.roles = data.roles ?? []
      this.referralBranches = data.referral_branches ?? []
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
