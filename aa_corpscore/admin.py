"""Django admin registration for AA CorpScore."""

from django.contrib import admin

from aa_corpscore.models import (
    Achievement,
    DiscordActivityDaily,
    HardInquiry,
    MemberAchievement,
    ScoreComponentSnapshot,
    ScoreEvent,
    ScoreSettings,
    ScoreSnapshot,
)


@admin.register(ScoreSettings)
class ScoreSettingsAdmin(admin.ModelAdmin):
    list_display = ("name", "last_recomputed_at")
    fieldsets = (
        ("Component weights (must sum to 100)", {
            "fields": (
                "weight_alliance_fat", "weight_corp_fat", "weight_activity",
                "weight_corptools", "weight_discord", "weight_srp", "weight_pvp",
                "weight_memberstatus", "weight_industrypool",
            ),
        }),
        ("Decay windows (days)", {
            "fields": (
                "decay_window_alliance_fat", "decay_window_corp_fat",
                "decay_window_activity", "decay_window_discord", "decay_window_pvp",
                "decay_window_memberstatus", "decay_window_industrypool",
            ),
        }),
        ("zKillboard PvP integration", {
            "fields": ("zkill_enabled",),
            "description": "When enabled, the PvP adapter queries the zKillboard "
                           "Statistics API for each member's kill/loss history. "
                           "Set weight_pvp above 0 for it to affect scores. "
                           "Off by default to avoid unnecessary API calls.",
        }),
        ("Tier cutoffs (lower bound inclusive)", {
            "fields": ("tier_subprime", "tier_fair", "tier_prime", "tier_elite", "tier_blackcard"),
        }),
        ("Group gating", {
            "fields": ("group_gating_enabled", "elite_group", "subprime_group"),
        }),
        ("Hard inquiries", {
            "fields": (
                "log_hard_inquiries", "hard_inquiry_penalty",
                "hard_inquiry_penalty_window_days", "hard_inquiry_penalty_max",
            ),
        }),
        ("ShipFinance integration", {
            "fields": (
                "shipfinance_enabled",
                "shipfinance_min_score_finance", "shipfinance_min_score_rent",
            ),
            "description": "When enabled, the member's CorpScore tier affects "
                           "their ShipFinance interest rates, insurance premiums, "
                           "and eligibility. Like real-life credit scores affecting "
                           "loan terms. Requires aa-shipfinance to be installed "
                           "and its code to call CorpScore's public API.",
        }),
        ("ShipFinance interest rate adjustments (percentage points)", {
            "fields": (
                "shipfinance_rate_adj_subprime", "shipfinance_rate_adj_fair",
                "shipfinance_rate_adj_prime", "shipfinance_rate_adj_elite",
                "shipfinance_rate_adj_blackcard",
            ),
            "description": "Added to the base interest rate from ShipFinance's "
                           "offer config. Positive = premium (subprime pays more), "
                           "negative = discount (Black Card pays less).",
        }),
        ("ShipFinance insurance premium adjustments (percentage points)", {
            "fields": (
                "shipfinance_insurance_adj_subprime", "shipfinance_insurance_adj_fair",
                "shipfinance_insurance_adj_prime", "shipfinance_insurance_adj_elite",
                "shipfinance_insurance_adj_blackcard",
            ),
            "description": "Added to the base insurance premium rate. "
                           "Risky borrowers pay more for insurance.",
        }),
        ("Recompute", {
            "fields": ("recompute_interval_hours", "last_recomputed_at"),
        }),
    )


@admin.register(ScoreSnapshot)
class ScoreSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "score", "tier", "computed_at", "trigger")
    list_filter = ("tier", "trigger")
    search_fields = ("user__username",)
    readonly_fields = ("computed_at",)


@admin.register(ScoreComponentSnapshot)
class ScoreComponentSnapshotAdmin(admin.ModelAdmin):
    list_display = ("snapshot", "component", "normalised", "weight", "points")
    list_filter = ("component",)


@admin.register(HardInquiry)
class HardInquiryAdmin(admin.ModelAdmin):
    list_display = ("subject", "pulled_by", "pulled_at", "reason")
    search_fields = ("subject__username", "pulled_by__username")


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "description", "icon")


@admin.register(MemberAchievement)
class MemberAchievementAdmin(admin.ModelAdmin):
    list_display = ("user", "achievement", "awarded_at")
    search_fields = ("user__username",)


@admin.register(ScoreEvent)
class ScoreEventAdmin(admin.ModelAdmin):
    list_display = ("user", "delta", "label", "component", "occurred_at")
    list_filter = ("component",)
    search_fields = ("user__username",)


@admin.register(DiscordActivityDaily)
class DiscordActivityDailyAdmin(admin.ModelAdmin):
    list_display = ("discord_uid", "date", "message_count", "voice_minutes", "last_seen")
    list_filter = ("date",)
    search_fields = ("discord_uid",)
    ordering = ("-date",)
