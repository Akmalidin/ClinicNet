import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../pages/LoginPage.vue') },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('../pages/DashboardPage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/patients/:id',
    name: 'patient-card',
    component: () => import('../pages/PatientCardPage.vue'),
    props: true,
    meta: { requiresAuth: true },
  },
  {
    path: '/schedule',
    name: 'schedule',
    component: () => import('../pages/SchedulePage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/operations/:id',
    name: 'operation-checklist',
    component: () => import('../pages/OperationChecklistPage.vue'),
    props: true,
    meta: { requiresAuth: true },
  },
  {
    path: '/roles',
    name: 'rbac-admin',
    component: () => import('../pages/RbacAdminPage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/churn',
    name: 'churn-alerts',
    component: () => import('../pages/ChurnAlertsPage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/stock',
    name: 'warehouse-stock',
    component: () => import('../pages/WarehouseStockPage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/invoices/:id',
    name: 'billing-invoice',
    component: () => import('../pages/BillingInvoicePage.vue'),
    props: true,
    meta: { requiresAuth: true },
  },
  {
    path: '/staff',
    name: 'staff-hr',
    component: () => import('../pages/StaffHrPage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/triage',
    name: 'triage-queue',
    component: () => import('../pages/TriageQueuePage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/patients/:id/admit',
    name: 'admission-intake',
    component: () => import('../pages/AdmissionIntakePage.vue'),
    props: true,
    meta: { requiresAuth: true },
  },
  {
    path: '/beds',
    name: 'bed-management',
    component: () => import('../pages/BedManagementPage.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// All navigation — including the redirect after login/logout — goes
// through router.push/replace, never window.location: that's what keeps
// switching between sections an in-app transition instead of a full page
// reload.
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'dashboard' }
  }
  return true
})

export default router
