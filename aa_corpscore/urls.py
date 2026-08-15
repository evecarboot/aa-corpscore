from django.urls import path

from aa_corpscore.views import (
    AdminDashboardView,
    LeaderboardView,
    MemberBreakdownView,
    ScoreCardView,
    ScoreHistoryAPI,
    ShipFinanceTermsAPI,
    StatementView,
    WhatIfView,
)

app_name = "aa_corpscore"

urlpatterns = [
    path("", ScoreCardView.as_view(), name="scorecard"),
    path("leaderboard/", LeaderboardView.as_view(), name="leaderboard"),
    path("statement/", StatementView.as_view(), name="statement"),
    path("what-if/", WhatIfView.as_view(), name="whatif"),
    path("admin/", AdminDashboardView.as_view(), name="admin_dashboard"),
    path("member/<int:user_id>/", MemberBreakdownView.as_view(), name="member_breakdown"),
    path("api/history/", ScoreHistoryAPI.as_view(), name="api_history"),
    path("api/shipfinance/<int:user_id>/", ShipFinanceTermsAPI.as_view(), name="api_shipfinance"),
]
