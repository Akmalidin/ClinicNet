import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Dev server proxies /api straight to the Django dev server so the browser
// sees one origin (no CORS dance, no separate API base URL to configure per
// environment). In production the built assets are served by nginx, which
// does the same /api -> gunicorn proxying at the web-server level — see
// deploy/nginx/clinicnet-stom-asia.
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
