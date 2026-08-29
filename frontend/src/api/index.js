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
  list: (params) => client.get('appointments/', { params }),
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

export const notificationsApi = {
  list: (params) => client.get('notifications/', { params }),
  markRead: (id) => client.patch(`notifications/${id}/`, { is_read: true }),
}
