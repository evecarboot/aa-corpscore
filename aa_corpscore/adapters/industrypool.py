"""IndustryPool adapter - reads industry job contributions from aa-industrypool.

If [aa-industrypool](https://github.com/evecarboot/aa-industrypool) is installed,
this adapter counts the member's completed/delivered industry jobs within the
decay window. Members who contribute to corp industry (manufacturing, reactions,
invention, research) get a score boost.

This rewards members who contribute beyond just showing up to fleets - the
industrial backbone of the corp.
"""

from datetime import timedelta

from django.utils import timezone

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult

# Soft cap: 10 completed jobs in the window = 100/100.
JOB_SOFT_CAP = 10.0


class IndustryPoolAdapter(BaseAdapter):
    component = "industrypool"

    def available(self) -> bool:
        try:
            import industrypool.models  # noqa: F401
            return True
        except Exception:
            return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="completed jobs")
        window_days = settings.decay_windows().get(self.component, 90)
        cutoff = timezone.now() - timedelta(days=window_days)

        try:
            from industrypool.models import JobRequest, JobRequestStatus
        except Exception:
            result.normalised = 50.0
            result.note = "IndustryPool not available"
            return result

        # Count jobs this user built (claimed or assigned) that were delivered
        # or completed within the decay window.
        completed_jobs = JobRequest.objects.filter(
            status__in=[JobRequestStatus.DELIVERED, JobRequestStatus.COMPLETED],
            delivered_at__gte=cutoff,
        ).filter(
            claimed_by=user,
        ) | JobRequest.objects.filter(
            status__in=[JobRequestStatus.DELIVERED, JobRequestStatus.COMPLETED],
            delivered_at__gte=cutoff,
            assigned_to=user,
        )

        count = completed_jobs.count()
        result.raw_value = float(count)

        if count == 0:
            result.normalised = 0.0
            result.note = f"No completed industry jobs in {window_days}d"
        else:
            result.normalised = min(100.0, (count / JOB_SOFT_CAP) * 100.0)
            result.note = f"{count} completed job(s) in {window_days}d"

        return result
