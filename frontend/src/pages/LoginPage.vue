<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.push(route.query.redirect || { name: 'dashboard' })
  } catch (e) {
    error.value =
      e.response?.data?.detail || 'Не удалось войти. Проверьте логин и пароль.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="mockup-page" style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(160deg,#1F3A52 0%,#16283A 100%)">
    <form
      style="width:400px;background:var(--card);border-radius:20px;padding:40px 36px;box-shadow:0 30px 80px rgba(0,0,0,0.35)"
      @submit.prevent="submit"
    >
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:30px">
        <div style="width:38px;height:38px;border-radius:10px;background:var(--mint);display:flex;align-items:center;justify-content:center;font-family:'Fraunces',serif;font-weight:700;color:#fff;font-size:16px">C</div>
        <div style="font-family:'Fraunces',serif;font-weight:600;font-size:19px;color:var(--navy)">ClinicNet</div>
      </div>
      <h2 style="font-size:21px;color:var(--navy);margin-bottom:6px">Вход в систему</h2>
      <div style="font-size:12.5px;color:var(--ink-soft);margin-bottom:26px">Единая сеть клиник</div>

      <div style="margin-bottom:16px">
        <span style="font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;color:var(--ink-soft);margin-bottom:6px;display:block">Логин</span>
        <input
          v-model="username"
          autocomplete="username"
          required
          style="width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--line);font-size:13.5px;color:var(--ink)"
        />
      </div>
      <div style="margin-bottom:20px">
        <span style="font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;color:var(--ink-soft);margin-bottom:6px;display:block">Пароль</span>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          style="width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--line);font-size:13.5px;color:var(--ink)"
        />
      </div>

      <p v-if="error" style="font-size:13px;color:var(--red);margin-bottom:12px">{{ error }}</p>

      <button
        type="submit"
        :disabled="submitting"
        style="width:100%;padding:14px;border-radius:10px;background:var(--navy);color:#fff;border:none;font-size:14px;font-weight:700;cursor:pointer"
      >
        {{ submitting ? 'Входим…' : 'Войти' }}
      </button>
      <div style="text-align:center;font-size:11.5px;color:var(--ink-soft);margin-top:20px">
        Забыли пароль? Обратитесь к администратору филиала
      </div>
    </form>
  </div>
</template>
