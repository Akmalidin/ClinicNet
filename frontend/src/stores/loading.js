import { defineStore } from 'pinia'

// A single source of truth for "is anything in flight right now" so any
// component can show a loading state without each one tracking its own
// axios call — this is what the requirement "переключения/изменения не
// должны требовать внешней перезагрузки, при загрузке — анимация" is built
// on: api/client.js bumps/drops this counter around every request, and
// App.vue renders a global spinner overlay whenever it's non-zero.
export const useLoadingStore = defineStore('loading', {
  state: () => ({
    activeRequests: 0,
  }),
  getters: {
    isLoading: (state) => state.activeRequests > 0,
  },
  actions: {
    start() {
      this.activeRequests += 1
    },
    stop() {
      this.activeRequests = Math.max(0, this.activeRequests - 1)
    },
  },
})
