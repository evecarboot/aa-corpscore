"""Views for AA CorpScore.

Member-facing:
- ScoreCardView: the personal Credit-Karma-style score card.
- StatementView: the meme monthly statement.
- WhatIfView: the score simulator.

Leadership-facing:
- LeaderboardView: corp-wide ranked list + distribution histogram.
- MemberBreakdownView: a hard pull on another member's full breakdown.
- AdminDashboardView: recompute trigger + settings summary.

API:
- ScoreHistoryAPI: sparkline data for the requesting user's score over time.
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import View

from aa_corpscore.models import (
    HardInquiry,
    MemberAchievement,
    SCORE_MAX,
    ScoreEvent,
    ScoreSnapshot,
)
from aa_corpscore import services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_basic_access(request):
    return (
        request.user.is_authenticated
        and request.user.has_perm("aa_corpscore.basic_access")
    )


def _components_for_snapshot(snapshot):
    return list(snapshot.components.all())


# ---------------------------------------------------------------------------
# Member-facing
# ---------------------------------------------------------------------------

class ScoreCardView(UserPassesTestMixin, View):
    """The personal score card - the meme centerpiece."""

    def test_func(self):
        return _has_basic_access(self.request)

    def get(self, request):
        user = request.user
        snapshot = services.latest_snapshot(user)
        components = _components_for_snapshot(snapshot) if snapshot else []
        history = services.snapshot_history(user, limit=30)
        achievements = list(MemberAchievement.objects.filter(user=user).select_related("achievement"))
        hard_inquiries = []
        if services.get_settings().log_hard_inquiries:
            cutoff = timezone.now() - timedelta(days=30)
            hard_inquiries = list(
                HardInquiry.objects.filter(subject=user, pulled_at__gte=cutoff).order_by("-pulled_at")
            )

        # Split components into helping (>=70), hurting (<40), neutral (40-69).
        helping_components = [c for c in components if c.normalised >= 70]
        hurting_components = [c for c in components if c.normalised < 40]
        neutral_components = [c for c in components if 40 <= c.normalised < 70]

        # Build sparkline points (oldest -> newest).
        spark = [
            {"x": i, "score": s.score, "tier": s.tier}
            for i, s in enumerate(reversed(history))
        ]

        context = {
            "title": "My CorpScore",
            "snapshot": snapshot,
            "components": components,
            "helping_components": helping_components,
            "hurting_components": hurting_components,
            "neutral_components": neutral_components,
            "achievements": achievements,
            "hard_inquiries": hard_inquiries,
            "spark": spark,
            "tier_label": services.tier_label(snapshot.tier) if snapshot else "No score yet",
            "tier_color": services.tier_color(snapshot.tier) if snapshot else "#95a5a6",
        }
        from aa_corpscore.models import SCORE_MAX, SCORE_MIN
        context["score_min"] = SCORE_MIN
        context["score_max"] = SCORE_MAX
        return render(request, "aa_corpscore/scorecard.html", context)


class StatementView(UserPassesTestMixin, View):
    """The meme monthly statement."""

    def test_func(self):
        return _has_basic_access(self.request)

    def get(self, request):
        user = request.user
        days = int(request.GET.get("days", 30))
        cutoff = timezone.now() - timedelta(days=days)
        events = list(ScoreEvent.objects.filter(user=user, occurred_at__gte=cutoff).order_by("-occurred_at"))
        snapshot = services.latest_snapshot(user)

        context = {
            "title": "My Statement",
            "snapshot": snapshot,
            "events": events,
            "days": days,
            "score_max": SCORE_MAX,
            "tier_label": services.tier_label(snapshot.tier) if snapshot else "",
            "tier_color": services.tier_color(snapshot.tier) if snapshot else "#95a5a6",
        }
        return render(request, "aa_corpscore/statement.html", context)


class WhatIfView(UserPassesTestMixin, View):
    """Score simulator: member can fiddle component values and see projected score."""

    def test_func(self):
        return _has_basic_access(self.request)

    def get(self, request):
        from aa_corpscore.adapters import available_components
        from aa_corpscore.models import DEFAULT_WEIGHTS

        settings = services.get_settings()
        weights = settings.weights()
        available = available_components()

        # Read overrides from query params (component=value 0-100).
        overrides = {}
        for key in weights:
            val = request.GET.get(key)
            if val is not None and val != "":
                try:
                    overrides[key] = max(0.0, min(100.0, float(val)))
                except ValueError:
                    pass

        projected_score = None
        projected_tier = None
        if overrides:
            projected_score, projected_tier = services.what_if(request.user, overrides)

        # Current values for the sliders.
        snapshot = services.latest_snapshot(request.user)
        current = {}
        if snapshot:
            for c in snapshot.components.all():
                current[c.component] = c.normalised

        context = {
            "title": "Score Simulator",
            "weights": weights,
            "available": available,
            "current": current,
            "overrides": overrides,
            "projected_score": projected_score,
            "projected_tier": services.tier_label(projected_tier) if projected_tier else None,
            "projected_tier_color": services.tier_color(projected_tier) if projected_tier else None,
            "current_score": snapshot.score if snapshot else None,
            "current_tier": services.tier_label(snapshot.tier) if snapshot else None,
            "score_max": SCORE_MAX,
        }
        return render(request, "aa_corpscore/whatif.html", context)


# ---------------------------------------------------------------------------
# Leadership-facing
# ---------------------------------------------------------------------------

class LeaderboardView(UserPassesTestMixin, View):
    """Corp-wide ranked leaderboard + tier distribution histogram."""

    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.has_perm("aa_corpscore.view_leaderboard")
        )

    def get(self, request):
        limit = int(request.GET.get("limit", 100))
        entries = services.leaderboard(limit=limit)
        distribution = services.score_distribution()

        # Annotate each entry with tier label/color for the template.
        for e in entries:
            e.tier_label = services.tier_label(e.tier)
            e.tier_color = services.tier_color(e.tier)

        context = {
            "title": "Corp Leaderboard",
            "entries": entries,
            "distribution": distribution,
            "tier_labels": {
                "subprime": services.tier_label("subprime"),
                "fair": services.tier_label("fair"),
                "prime": services.tier_label("prime"),
                "elite": services.tier_label("elite"),
                "blackcard": services.tier_label("blackcard"),
            },
            "tier_colors": {
                "subprime": services.tier_color("subprime"),
                "fair": services.tier_color("fair"),
                "prime": services.tier_color("prime"),
                "elite": services.tier_color("elite"),
                "blackcard": services.tier_color("blackcard"),
            },
        }
        return render(request, "aa_corpscore/leaderboard.html", context)


class MemberBreakdownView(UserPassesTestMixin, View):
    """A 'hard pull' on another member's full score breakdown.

    Logs a HardInquiry and shows the full component breakdown. Requires the
    view_breakdown permission.
    """

    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.has_perm("aa_corpscore.view_breakdown")
        )

    def get(self, request, user_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        subject = get_object_or_404(User, pk=user_id)
        snapshot = services.latest_snapshot(subject)
        components = _components_for_snapshot(snapshot) if snapshot else []
        achievements = list(MemberAchievement.objects.filter(user=subject).select_related("achievement"))

        # Log the hard pull.
        services.log_hard_inquiry(
            subject=subject,
            pulled_by=request.user,
            reason=f"Breakdown viewed by {request.user}",
        )

        context = {
            "title": f"Breakdown - {subject.username}",
            "subject": subject,
            "snapshot": snapshot,
            "components": components,
            "achievements": achievements,
            "score_max": SCORE_MAX,
            "tier_label": services.tier_label(snapshot.tier) if snapshot else "No score yet",
            "tier_color": services.tier_color(snapshot.tier) if snapshot else "#95a5a6",
        }
        return render(request, "aa_corpscore/member_breakdown.html", context)


class AdminDashboardView(UserPassesTestMixin, View):
    """Admin dashboard: settings summary + manual recompute trigger."""

    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.has_perm("aa_corpscore.manage_settings")
        )

    def get(self, request):
        settings = services.get_settings()
        from aa_corpscore.adapters import available_components
        context = {
            "title": "CorpScore Admin",
            "settings": settings,
            "available_components": available_components(),
            "weights": settings.weights(),
            "last_recomputed_at": settings.last_recomputed_at,
        }
        return render(request, "aa_corpscore/admin_dashboard.html", context)

    def post(self, request):
        if not request.user.has_perm("aa_corpscore.trigger_recompute"):
            messages.error(request, "You do not have permission to trigger a recompute.")
            return redirect("aa_corpscore:admin_dashboard")
        from aa_corpscore.tasks import recompute_all_scores
        recompute_all_scores.delay(trigger="manual")
        messages.success(request, "Score recompute queued.")
        return redirect("aa_corpscore:admin_dashboard")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ScoreHistoryAPI(UserPassesTestMixin, View):
    """Return the requesting user's score history as JSON for the sparkline."""

    def test_func(self):
        return _has_basic_access(self.request)

    def get(self, request):
        history = services.snapshot_history(request.user, limit=90)
        data = [
            {
                "computed_at": s.computed_at.isoformat(),
                "score": s.score,
                "tier": s.tier,
                "trigger": s.trigger,
            }
            for s in reversed(history)
        ]
        return JsonResponse({"history": data})


class ShipFinanceTermsAPI(View):
    """REST API endpoint for ShipFinance (and other integrations) to query
    a member's adjusted finance terms via HTTP instead of Python imports.

    GET /aa-corpscore/api/shipfinance/<user_id>/?base_rate=10&base_insurance=5

    Returns JSON:
        {
            "eligible": true,
            "ineligible_reason": "",
            "score": 720,
            "tier": "prime",
            "tier_label": "Prime Member",
            "base_interest_rate": "10",
            "adjusted_interest_rate": "10",
            "rate_adjustment": "0",
            "base_insurance_premium": "5",
            "adjusted_insurance_premium": "5",
            "insurance_adjustment": "0"
        }

    Authentication: requires the `aa_corpscore.api_access` permission or
    superuser. This is intended for server-to-server calls (e.g. aa-shipfinance
    making an internal HTTP request), not for member-facing pages.
    """

    def _has_api_access(self, request):
        if not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.has_perm("aa_corpscore.api_access")
            or request.user.has_perm("aa_corpscore.manage_settings")
        )

    def get(self, request, user_id):
        if not self._has_api_access(request):
            return JsonResponse({"error": "Unauthorized"}, status=403)

        from django.contrib.auth import get_user_model
        from decimal import Decimal, InvalidOperation
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found"}, status=404)

        try:
            base_rate = Decimal(str(request.GET.get("base_rate", "10")))
            base_insurance = Decimal(str(request.GET.get("base_insurance", "5")))
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid base_rate or base_insurance"}, status=400)

        from aa_corpscore.shipfinance import get_finance_terms
        terms = get_finance_terms(user, base_rate, base_insurance)

        return JsonResponse({
            "eligible": terms.eligible,
            "ineligible_reason": terms.ineligible_reason,
            "score": terms.score,
            "tier": terms.tier,
            "tier_label": terms.tier_label,
            "base_interest_rate": str(terms.base_interest_rate),
            "adjusted_interest_rate": str(terms.adjusted_interest_rate),
            "rate_adjustment": str(terms.rate_adjustment),
            "base_insurance_premium": str(terms.base_insurance_premium),
            "adjusted_insurance_premium": str(terms.adjusted_insurance_premium),
            "insurance_adjustment": str(terms.insurance_adjustment),
        })
