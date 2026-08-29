import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './style.css'

const app = createApp(App)
app.use(createPinia())

// Router's first navigation guard (router/index.js) runs as soon as the
// router is installed, so restore() has to finish — and settle whether a
// stored token is actually still valid — before that happens; otherwise a
// refresh of the page while logged in would bounce through /login for one
// frame with a real session underneath. (.then() rather than top-level
// await — the latter needs a newer build target than Vite's default.)
const auth = useAuthStore()
auth.restore().then(() => {
  app.use(router)
  app.mount('#app')
})
