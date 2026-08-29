<script setup>
// Small icon + tooltip for an appointment card in the schedule, shown only
// when the appointment was created from a Referral (spec step 8) — lets a
// receptionist/doctor see at a glance "this isn't a walk-in, it came from
// a referral" without opening the appointment. `referral` is the
// AppointmentSerializer's `referral` field (apps/scheduling/serializers.py)
// — null for a normal appointment, in which case this renders nothing.
defineProps({
  referral: { type: Object, default: null },
})
</script>

<template>
  <span v-if="referral" class="relative inline-flex group align-middle ml-1">
    <span
      class="inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary-light text-primary text-[10px] leading-none cursor-help"
      aria-label="Из направления"
    >
      ↪
    </span>
    <span
      class="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block
             whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs text-white z-10"
    >
      Из направления · {{ referral.from_doctor_name }}: «{{ referral.reason }}»
    </span>
  </span>
</template>
