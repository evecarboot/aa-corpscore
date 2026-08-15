"""Activity adapter - measures general auth activity and tenure.

Uses the user's last login date and date joined as proxies for engagement when
no richer activity source is available. Tenure rewards long-standing members.
"""

from datetime import timedelta

from django.utils import timezone

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult


class ActivityAdapter(BaseAdapter):
    component = "activity"

    def available(self) -> bool:
        # Always available - uses core Django auth fields.
        return True

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="activity score")
        now = timezone.now()

        # Recency: full marks if logged in within 7 days, decays to 0 over the
        # configured activity decay window.
        window_days = settings.decay_windows().get(self.component, 180)
        last_login = getattr(user, "last_login", None)
        if last_login:
            days_since = max(0, (now - last_login).days)
            recency = max(0.0, 1.0 - (days_since / max(1, window_days)))
        else:
            recency = 0.0

        # Tenure: 1 point per week of membership, capped at 52 weeks (1 year).
        date_joined = getattr(user, "date_joined", None) or now
        tenure_weeks = min(52, max(0, (now - date_joined).days // 7))
        tenure = tenure_weeks / 52.0

        # Blend: 70% recency, 30% tenure, scaled to 0-100.
        result.raw_value = (recency * 0.7 + tenure * 0.3) * 100
        result.normalised = result.raw_value
        result.note = (
            f"Last login {last_login:%Y-%m-%d} " if last_login else "Never logged in "
        ) + f"| {tenure_weeks}w tenure"
        return result
