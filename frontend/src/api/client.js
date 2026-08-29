import axios from 'axios'

import { useLoadingStore } from '../stores/loading'

const client = axios.create({
  baseURL: '/api/v1/',
  headers: { 'Content-Type': 'application/json' },
})

// Kept out of Pinia deliberately: this is read/written on every single
// request (including the ones fired before Pinia/vue-router have anything
// else to say about auth state), so a plain module-level pair of strings
// backed by localStorage is simpler than routing it through a store here.
// stores/auth.js is the place that owns *deciding* login/logout; this file
// only carries the token bytes.
const ACCESS_KEY = 'clinicnet.access'
const REFRESH_KEY = 'clinicnet.refresh'

export function getTokens() {
  return {
    access: localStorage.getItem(ACCESS_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
  }
}

export function setTokens({ access, refresh }) {
  if (access) localStorage.setItem(ACCESS_KEY, access)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

client.interceptors.request.use((config) => {
  // Pinia is installed before the app mounts (see main.js), and no request
  // fires before that, so this is always safe despite being a lazy lookup.
  useLoadingStore().start()
  const { access } = getTokens()
  if (access) {
    config.headers.Authorization = `Bearer ${access}`
  }
  return config
})

function stopLoading(value) {
  useLoadingStore().stop()
  return value
}

let refreshInFlight = null

client.interceptors.response.use(
  (response) => stopLoading(response),
  async (error) => {
    const { config, response } = error
    const isAuthEndpoint = config?.url?.startsWith('auth/token')

    if (response?.status === 401 && !isAuthEndpoint && !config._retried) {
      const { refresh } = getTokens()
      if (refresh) {
        try {
          // Multiple requests can 401 at once (e.g. a page that fires
          // several API calls in parallel) — share one refresh call
          // instead of racing several TokenRefreshView hits.
          refreshInFlight ??= axios
            .post('/api/v1/auth/token/refresh/', { refresh })
            .finally(() => {
              refreshInFlight = null
            })
          const { data } = await refreshInFlight
          setTokens({ access: data.access })
          config._retried = true
          config.headers.Authorization = `Bearer ${data.access}`
          const retried = await client(config)
          return stopLoading(retried)
        } catch {
          // Refresh token itself is dead — fall through to the
          // unrecoverable-auth-failure path below.
        }
      }
      clearTokens()
      // No hard navigation (window.location) — App.vue listens for this
      // and routes to /login via vue-router, keeping the whole session
      // switch inside the SPA instead of a full page reload.
      window.dispatchEvent(new CustomEvent('clinicnet:auth-failure'))
    }

    stopLoading()
    return Promise.reject(error)
  },
)

export default client
