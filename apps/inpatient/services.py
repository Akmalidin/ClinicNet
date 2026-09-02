from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Admission, AdmissionReason, AdmissionStatus, Bed, BedStatus, Transfer


def admit_patient(
    *, patient, department, bed, attending_doctor, admitted_by, diagnosis_at_admission,
    reason=AdmissionReason.PLANNED, notes="", admitted_at=None,
):
    """Creates an ACTIVE Admission and occupies its bed as one atomic
    step — same "validate everything, write everything, or neither"
    discipline as apps.inventory.services.consume_for_visit. The bed's
    OCCUPIED status is a side effect of admission, never set directly
    through the API (see Bed's docstring) — this is the one place that
    sets it.
    """
    if bed.status not in (BedStatus.FREE, BedStatus.RESERVED):
        raise ValidationError(
            {"bed": f"Койка недоступна для госпитализации (статус: {bed.get_status_display()})."}
        )

    admission = Admission(
        patient=patient,
        department=department,
        bed=bed,
        attending_doctor=attending_doctor,
        admitted_by=admitted_by,
        diagnosis_at_admission=diagnosis_at_admission,
        reason=reason,
        notes=notes,
        status=AdmissionStatus.ACTIVE,
    )
    if admitted_at is not None:
        admission.admitted_at = admitted_at
    admission.full_clean()

    with transaction.atomic():
        admission.save()
        Bed.objects.filter(pk=bed.pk).update(status=BedStatus.OCCUPIED)

    return admission


def discharge_admission(admission: Admission, epicrisis: str = "") -> bool:
    """Discharges the admission and frees its bed (-> FREE, not CLEANING
    — staff mark cleaning explicitly afterwards via BedViewSet.set_status)
    as one atomic step. Returns False (no-op, matching Admission.discharge
    itself) without touching the bed if the admission was already
    terminal."""
    with transaction.atomic():
        changed = admission.discharge(epicrisis=epicrisis)
        if changed:
            Bed.objects.filter(pk=admission.bed_id).update(status=BedStatus.FREE)
    return changed


def transfer_admission(*, admission: Admission, to_department, to_bed, transferred_by, reason: str = "") -> Transfer:
    """Moves an ACTIVE admission to a new department/bed and logs a
    Transfer row, atomically: frees the old bed, occupies the new one,
    updates the admission's current location in place. Validates the
    target bed the same way admit_patient validates on intake (FREE/
    RESERVED only) — Admission.full_clean() additionally re-checks the
    bed-belongs-to-department and no-double-booking guards on the new
    location, since it's the same model-level invariant either way.
    """
    if admission.status != AdmissionStatus.ACTIVE:
        raise ValidationError("Перевод возможен только для активной госпитализации.")
    if to_bed.room.department_id != to_department.pk:
        raise ValidationError({"to_bed": "Койка не принадлежит указанному отделению."})
    if to_bed.pk == admission.bed_id:
        raise ValidationError({"to_bed": "Пациент уже на этой койке."})
    if to_bed.status not in (BedStatus.FREE, BedStatus.RESERVED):
        raise ValidationError(
            {"to_bed": f"Койка недоступна для перевода (статус: {to_bed.get_status_display()})."}
        )

    from_department = admission.department
    from_bed = admission.bed

    admission.department = to_department
    admission.bed = to_bed
    admission.full_clean()

    with transaction.atomic():
        admission.save(update_fields=["department", "bed", "updated_at"])
        Bed.objects.filter(pk=from_bed.pk).update(status=BedStatus.FREE)
        Bed.objects.filter(pk=to_bed.pk).update(status=BedStatus.OCCUPIED)
        transfer = Transfer.objects.create(
            admission=admission,
            from_department=from_department,
            from_bed=from_bed,
            to_department=to_department,
            to_bed=to_bed,
            reason=reason,
            transferred_by=transferred_by,
        )

    return transfer
