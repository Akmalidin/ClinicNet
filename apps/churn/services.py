"""apps.churn.services.calculate_churn_risks — the actual heuristic.

Not a Celery task: this project deliberately has no Celery/Redis (see
docs/PHASE2-REFERRALS-DESIGN.md — standing up that infrastructure for a
handful of scheduled jobs was judged overkill). The existing scheduled-job
pattern is a management command run under cron, same as
apps.referrals.management.commands.escalate_stale_referrals — this module
is called from apps.churn.management.commands.calculate_churn_risks, which
is meant to run under cron the same way.
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from apps.visits.models import Visit, VisitStatus

from .models import ChurnRisk, ChurnRiskStatus

MIN_VISITS_FOR_HEURISTIC = 2


def calculate_churn_risks() -> dict:
    """For every patient with at least MIN_VISITS_FOR_HEURISTIC completed
    visits, computes their average inter-visit interval and how many days
    overdue they are past it. Idempotent, safe to re-run: an existing
    active (NEW/ACKNOWLEDGED) alert is refreshed in place, not duplicated;
    a patient who has since come back (a completed visit after the alert's
    last_visit_date) gets their active alert auto-REACTIVATED, so the
    coordinator doesn't have to close it by hand every run.
    """
    created = updated = reactivated = skipped_degenerate = 0

    patient_ids = (
        Visit.objects.filter(status=VisitStatus.COMPLETED)
        .values("patient_id")
        .annotate(visit_count=Count("id"))
        .filter(visit_count__gte=MIN_VISITS_FOR_HEURISTIC)
        .values_list("patient_id", flat=True)
    )

    now = timezone.now()

    for patient_id in patient_ids:
        visits = list(
            Visit.objects.filter(patient_id=patient_id, status=VisitStatus.COMPLETED)
            .order_by("created_at")
            .values_list("created_at", "branch_id")
        )
        dates = [v[0] for v in visits]
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_interval_days = sum(intervals) / len(intervals)
        if avg_interval_days <= 0:
            # All completed visits landed the same day (or clock skew) —
            # no meaningful "usual interval" to be overdue against.
            skipped_degenerate += 1
            continue

        last_visit_date = dates[-1]
        last_branch_id = visits[-1][1]
        days_since = (now - last_visit_date).days
        days_overdue = days_since - int(avg_interval_days)

        existing = ChurnRisk.objects.filter(
            patient_id=patient_id, status__in=(ChurnRiskStatus.NEW, ChurnRiskStatus.ACKNOWLEDGED)
        ).first()

        if days_overdue <= 0:
            # Not overdue as of the latest completed visit — if there's
            # an active alert from a previous run, the patient came back.
            if existing is not None:
                existing.reactivate()
                reactivated += 1
            continue

        risk_score = round(days_overdue / avg_interval_days, 2)

        if existing is not None:
            existing.last_visit_date = last_visit_date
            existing.avg_interval_days = avg_interval_days
            existing.days_overdue = days_overdue
            existing.risk_score = risk_score
            existing.branch_id = last_branch_id
            existing.full_clean()
            existing.save()
            updated += 1
        else:
            risk = ChurnRisk(
                patient_id=patient_id,
                branch_id=last_branch_id,
                last_visit_date=last_visit_date,
                avg_interval_days=avg_interval_days,
                days_overdue=days_overdue,
                risk_score=risk_score,
                status=ChurnRiskStatus.NEW,
            )
            risk.full_clean()
            risk.save()
            created += 1

    return {
        "created": created,
        "updated": updated,
        "reactivated": reactivated,
        "skipped_degenerate": skipped_degenerate,
    }
