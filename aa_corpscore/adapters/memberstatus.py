"""MemberStatus adapter - reads inactivity/LOA status from aa-memberstatus.

If [aa-memberstatus](https://github.com/evecarboot/aa-memberstatus) is installed,
this adapter uses the member's inactivity status and leave-of-absence records as
a score component. Members who are active (not pinged for inactivity) score
high. Members with an active LOA get a neutral baseline (we don't penalise
people for taking planned breaks). Members who are currently pinged as inactive
score low.

This is a "soft" signal - it reflects whether the member is showing up to the
game at all, which is the most basic form of engagement.
"""

from datetime import timedelta

from django.utils import timezone

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult


class MemberStatusAdapter(BaseAdapter):
    component = "memberstatus"

    def available(self) -> bool:
        try:
            import memberstatus.models  # noqa: F401
            return True
        except Exception:
            return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="status")
        window_days = settings.decay_windows().get(self.component, 30)
        cutoff = timezone.now() - timedelta(days=window_days)

        try:
            from memberstatus.models import InactivityPing, LeaveOfAbsence
        except Exception:
            result.normalised = 50.0
            result.note = "MemberStatus not available"
            return result

        # Check for active leave of absence.
        active_loa = LeaveOfAbsence.objects.filter(
            user=user,
            start_date__lte=timezone.now().date(),
            end_date__gte=timezone.now().date(),
        ).exists()
        if active_loa:
            result.raw_value = 1
            result.normalised = 60.0  # neutral-positive: planned break
            result.note = "On leave of absence (no penalty)"
            return result

        # Check for recent inactivity pings.
        recent_pings = InactivityPing.objects.filter(
            user=user,
            timestamp__gte=cutoff,
        ).order_by("-timestamp")

        if recent_pings.exists():
            latest = recent_pings.first()
            # Inactive ping = low score. Warning ping = mild penalty.
            if latest.ping_type == "inactive":
                result.raw_value = 0
                result.normalised = 20.0
                result.note = f"Inactive (pinged {latest.timestamp:%Y-%m-%d})"
            else:
                result.raw_value = 0
                result.normalised = 45.0
                result.note = f"Inactivity warning ({latest.timestamp:%Y-%m-%d})"
            return result

        # No pings, no LOA = active member.
        result.raw_value = 1
        result.normalised = 90.0
        result.note = "Active (no inactivity pings)"
        return result
