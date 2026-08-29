import { defineStore } from 'pinia'

import { authApi, meApi } from '../api'
import { clearTokens, getTokens, setTokens } from '../api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    // roles: [{ role, branch_scope, branches }] — from MeView, drives the
    // client-side branch guard in ReferralQueueWidget (see its docstring):
    // never trust that the backend already filtered correctly, re-check
    // branch_scope/branches here before rendering another branch's rows.
    roles: [],
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
    },
    async fetchMe() {
      const { data } = await meApi.get()
      this.user = data
      this.roles = data.roles ?? []
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
