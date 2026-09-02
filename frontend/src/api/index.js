import client from './client'

// Endpoint fields below are taken from the actual DRF serializers/views as
// of this commit (apps/*/serializers.py, apps/*/views.py) rather than only
// the spec doc — see docs/PHASE2-REFERRALS-DESIGN.md discrepancy #5 and the
// recon step this frontend slice started with.

export const authApi = {
  login: (username, password) => client.post('auth/token/', { username, password }),
}

export const meApi = {
  get: () => client.get('me/'),
}

export const branchesApi = {
  list: () => client.get('branches/'),
  // Every active branch in the network (id/name/code only) — NOT scoped by
  // branch.view like list() above. Needed for the cross-branch referral
  // picker: a plain doctor's branch.view only covers their own branch, but
  // routing a referral requires seeing every branch to route *to*. See
  // apps/branches/views.py BranchDirectoryView's docstring.
  directory: () => client.get('branches/directory/'),
}

export const patientsApi = {
  list: (params) => client.get('patients/', { params }),
  get: (id) => client.get(`patients/${id}/`),
}

export const visitsApi = {
  list: (params) => client.get('visits/', { params }),
  get: (id) => client.get(`visits/${id}/`),
}

export const appointmentsApi = {
  // Used by ReferralQueueWidget's "Забронировать" action: books the actual
  // calendar slot, then referralsApi.schedule() links it to the referral.
  create: (data) => client.post('appointments/', data),
  // params can include branch/doctor/patient/status (exact-match), date
  // (YYYY-MM-DD, whole-day filter — MultiBranchSchedulePage.vue), and
  // date_from/date_to (inclusive range — NetworkAnalyticsPage.vue's
  // 30-day booking funnel) — see AppointmentViewSet.get_queryset.
  list: (params) => client.get('appointments/', { params }),
  // Загрузка врачей за день (booked/available минут) — см.
  // AppointmentViewSet.utilization's докстринг.
  utilization: (date) => client.get('appointments/utilization/', { params: date ? { date } : {} }),
}

export const financeReportApi = {
  // apps.finance.views.FinanceReportView — per-branch payments/refunds
  // net total for an optional date range, scoped to finance.view branches.
  get: (params) => client.get('finance/report/', { params }),
  // apps.finance.views.LtvCohortReportView — patient LTV by quarter of
  // first visit, ALL-scope finance.view only (see the view's docstring).
  ltvCohorts: () => client.get('finance/ltv-cohorts/'),
}

export const specialtiesApi = {
  list: () => client.get('specialties/'),
}

export const doctorsApi = {
  // ?branch=<id> and/or ?specialty=<code> — see apps/accounts/views.py DoctorViewSet.
  list: (params) => client.get('doctors/', { params }),
}

export const referralsApi = {
  list: (params) => client.get('referrals/', { params }),
  get: (id) => client.get(`referrals/${id}/`),
  create: (data) => client.post('referrals/', data),
  availableSlots: (doctor, date) =>
    client.get('referrals/available_slots/', { params: { doctor, date } }),
  schedule: (id, targetAppointment) =>
    client.post(`referrals/${id}/schedule/`, { target_appointment: targetAppointment }),
  decline: (id, outcomeNote) => client.post(`referrals/${id}/decline/`, { outcome_note: outcomeNote }),
  complete: (id, outcomeNote) => client.post(`referrals/${id}/complete/`, { outcome_note: outcomeNote }),
}

export const triageApi = {
  list: (params) => client.get('triage-suggestions/', { params }),
  // override — необязательный { doctor, startsAt, endsAt } для "Изменить
  // слот": координатор подтверждает на другого врача/время, а не на то,
  // что предложил бот. Либо все три поля вместе, либо ни одного.
  confirm: (id, patientId, override) =>
    client.post(`triage-suggestions/${id}/confirm/`, {
      patient: patientId,
      ...(override
        ? { doctor: override.doctor, starts_at: override.startsAt, ends_at: override.endsAt }
        : {}),
    }),
  reject: (id, reason) => client.post(`triage-suggestions/${id}/reject/`, { reason }),
}

export const notificationsApi = {
  list: (params) => client.get('notifications/', { params }),
  markRead: (id) => client.patch(`notifications/${id}/`, { is_read: true }),
}

export const insurancePoliciesApi = {
  list: (params) => client.get('insurance-policies/', { params }),
}

export const invoicesApi = {
  // apps.finance.views.InvoiceViewSet — total_amount/patient_owed_amount/
  // paid_total/balance_due/is_paid are always computed, never stored
  // (see Invoice's model docstring).
  get: (id) => client.get(`invoices/${id}/`),
  pay: (id, data) => client.post(`invoices/${id}/pay/`, data),
}

export const stocksApi = {
  // apps.inventory.views.StockViewSet — on_hand_quantity/is_below_minimum
  // are always computed from the StockMovement ledger, never stored.
  list: (params) => client.get('stocks/', { params }),
  adjust: (id, data) => client.post(`stocks/${id}/adjust/`, data),
  // Every Stock row below its own min_quantity, scoped to this user's
  // branches — the network dashboard's "остаток < минимума" alert
  // source (see StockViewSet.low_stock's docstring: built for exactly
  // this).
  lowStock: () => client.get('stocks/low_stock/'),
}

export const churnApi = {
  // apps.churn.views.ChurnRiskViewSet — read-only + transitions (created
  // only by the calculate_churn_risks cron, never via POST here).
  list: (params) => client.get('churn-risks/', { params }),
  acknowledge: (id) => client.post(`churn-risks/${id}/acknowledge/`, {}),
  dismiss: (id) => client.post(`churn-risks/${id}/dismiss/`, {}),
}

export const staffApi = {
  // apps.accounts.views.StaffDirectoryView — network-wide, ALL-scope
  // gated (staff.view_network); a 403 here is expected for anyone but
  // network-admin, not a bug.
  list: () => client.get('staff/'),
}

export const rolesApi = {
  // apps.accounts.views.RoleViewSet — each role embeds its full nested
  // permissions (code/category/description), see RoleSerializer.
  list: () => client.get('roles/'),
}

export const admissionsApi = {
  // apps.inpatient.views.AdmissionViewSet
  list: (params) => client.get('admissions/', { params }),
  get: (id) => client.get(`admissions/${id}/`),
  create: (data) => client.post('admissions/', data),
  discharge: (id, epicrisis) => client.post(`admissions/${id}/discharge/`, { discharge_epicrisis: epicrisis }),
  // Отделения → палаты → койки (со статусом), доступные текущему
  // пользователю для госпитализации — department-scoped convenience
  // action, см. AdmissionViewSet.intake_options's докстринг: обычные
  // DepartmentViewSet/RoomViewSet/BedViewSet тут не подходят, они
  // branch-scoped, а зав.отделением/медсестра видят только свои
  // отделения через StaffDepartmentAssignment.
  intakeOptions: () => client.get('admissions/intake_options/'),
  // Отделения → палаты → койки с реальной занятостью (кто сейчас на
  // койке) — bedmanagement.html. .view-gated, шире круг, чем
  // intakeOptions (которое требует .manage) — координатор/врач/
  // медсестра, кому нужно просто видеть занятость.
  bedBoard: () => client.get('admissions/bed_board/'),
}

export const vitalsApi = {
  // apps.inpatient.views.VitalsRecordViewSet — append-only, create/list/
  // retrieve only (see the model's docstring), потому нет update/delete.
  list: (admissionId) => client.get('vitals-records/', { params: { admission: admissionId } }),
  create: (data) => client.post('vitals-records/', data),
}

export const operationsApi = {
  // apps.inpatient.views.OperationViewSet — checklist actions take no
  // body (POST {}), see apps/inpatient/tests.py's
  // test_full_checklist_flow_then_complete.
  get: (id) => client.get(`operations/${id}/`),
  signIn: (id) => client.post(`operations/${id}/sign_in/`, {}),
  timeOut: (id) => client.post(`operations/${id}/time_out/`, {}),
  signOut: (id) => client.post(`operations/${id}/sign_out/`, {}),
  complete: (id) => client.post(`operations/${id}/complete/`, {}),
}

export const labOrdersApi = {
  list: (params) => client.get('lab-orders/', { params }),
  create: (data) => client.post('lab-orders/', data),
  addResult: (id, data) => client.post(`lab-orders/${id}/result/`, data),
  cancel: (id) => client.post(`lab-orders/${id}/cancel/`),
}
