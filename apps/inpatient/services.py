from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Admission, AdmissionStatus, Bed, BedStatus


def admit_patient(*, patient, department, bed, attending_doctor, admitted_by, diagnosis_at_admission, admitted_at=None):
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
