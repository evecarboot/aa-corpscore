"""Models for AA CorpScore.

Stores per-user score snapshots, per-component breakdowns, hard inquiries
(leadership views of a member's full report), achievements, and admin-configurable
weights / tier cutoffs / decay windows.
"""

from django.conf import settings as django_settings
from django.contrib.auth.models import Group
from django.db import models

# ---------------------------------------------------------------------------
# Score scale constants (FICO-style meme). These are the defaults; tier cutoffs
# are overridable in ScoreSettings so a corp can tune the bands.
# ---------------------------------------------------------------------------
SCORE_MIN = 300
SCORE_MAX = 850

TIER_SUBPRIME = "subprime"
TIER_FAIR = "fair"
TIER_PRIME = "prime"
TIER_ELITE = "elite"
TIER_BLACKCARD = "blackcard"

TIER_CHOICES = [
    (TIER_SUBPRIME, "Subprime Capsuleer"),
    (TIER_FAIR, "Fair Weather Pilot"),
    (TIER_PRIME, "Prime Member"),
    (TIER_ELITE, "Elite Capsuleer"),
    (TIER_BLACKCARD, "Black Card / Concord-Verified"),
]

# Default tier cutoffs (lower bound inclusive). Must stay sorted ascending.
DEFAULT_TIER_CUTOFFS = {
    TIER_SUBPRIME: 300,
    TIER_FAIR: 580,
    TIER_PRIME: 670,
    TIER_ELITE: 740,
    TIER_BLACKCARD: 800,
}

# Default component weights. Must sum to 100 (enforced in admin validation).
# pvp defaults to 0 (off) - admin must enable zKillboard integration and assign
# a weight for PvP to affect scores.
DEFAULT_WEIGHTS = {
    "alliance_fat": 30,
    "corp_fat": 25,
    "activity": 15,
    "corptools": 10,
    "discord": 10,
    "srp": 10,
    "pvp": 0,
}


class General(models.Model):
    """Meta model for app permissions."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("basic_access", "Can access this app"),
            ("view_leaderboard", "Can view the corp score leaderboard"),
            ("view_breakdown", "Can view other members' full score breakdown (hard pull)"),
            ("manage_settings", "Can manage CorpScore settings"),
            ("trigger_recompute", "Can trigger a score recompute"),
            ("api_access", "Can access CorpScore REST API endpoints"),
        )


class ScoreSettings(models.Model):
    """Admin-configurable scoring settings. Singleton-style (use the first row)."""

    name = models.CharField(max_length=64, default="main", unique=True)

    # Component weights (0-100). Adapters whose weight is 0 are skipped.
    weight_alliance_fat = models.PositiveIntegerField(default=30)
    weight_corp_fat = models.PositiveIntegerField(default=25)
    weight_activity = models.PositiveIntegerField(default=15)
    weight_corptools = models.PositiveIntegerField(default=10)
    weight_discord = models.PositiveIntegerField(default=10)
    weight_srp = models.PositiveIntegerField(default=10)
    weight_pvp = models.PositiveIntegerField(default=0)
    weight_memberstatus = models.PositiveIntegerField(default=0)
    weight_industrypool = models.PositiveIntegerField(default=0)

    # Decay windows in days. Activity inside the window counts full; older
    # activity decays linearly to zero over the trailing window.
    decay_window_alliance_fat = models.PositiveIntegerField(default=90)
    decay_window_corp_fat = models.PositiveIntegerField(default=90)
    decay_window_activity = models.PositiveIntegerField(default=180)
    decay_window_discord = models.PositiveIntegerField(default=30)
    decay_window_pvp = models.PositiveIntegerField(default=90)
    decay_window_memberstatus = models.PositiveIntegerField(default=30)
    decay_window_industrypool = models.PositiveIntegerField(default=90)

    # zKillboard integration (off by default). When enabled, the PvP adapter
    # queries the zKillboard Statistics API for each member's characters.
    zkill_enabled = models.BooleanField(
        default=False,
        help_text="Enable zKillboard PvP data as a score component. "
                  "When off, the PvP adapter is skipped regardless of weight.",
    )

    # Tier cutoffs (lower bound inclusive).
    tier_subprime = models.PositiveIntegerField(default=300)
    tier_fair = models.PositiveIntegerField(default=580)
    tier_prime = models.PositiveIntegerField(default=670)
    tier_elite = models.PositiveIntegerField(default=740)
    tier_blackcard = models.PositiveIntegerField(default=800)

    # Optional group gating. Members at/above the elite cutoff are added to
    # elite_group; members below the fair cutoff are added to subprime_group.
    group_gating_enabled = models.BooleanField(default=False)
    elite_group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corpscore_elite",
    )
    subprime_group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corpscore_subprime",
    )

    # Recompute cadence (hours). The Celery beat task uses this as a fallback
    # if the default nightly schedule is not desired.
    recompute_interval_hours = models.PositiveIntegerField(default=24)

    # Hard-inquiry logging. When a leader views a member's full breakdown it
    # counts as a "hard pull" and is shown on the member's report.
    log_hard_inquiries = models.BooleanField(default=True)

    # Hard-inquiry impact: each hard pull in the last 30 days subtracts this
    # many points from the score (meme accuracy). 0 disables the penalty.
    hard_inquiry_penalty = models.PositiveIntegerField(default=2)
    hard_inquiry_penalty_window_days = models.PositiveIntegerField(default=30)
    hard_inquiry_penalty_max = models.PositiveIntegerField(default=10)

    # ------------------------------------------------------------------
    # ShipFinance integration (aa-shipfinance).
    # When enabled, CorpScore exposes a public API that ShipFinance calls
    # to adjust interest rates, insurance premiums, and eligibility based
    # on the member's CorpScore tier. Like real-life credit scores affecting
    # loan terms. Off by default.
    # ------------------------------------------------------------------
    shipfinance_enabled = models.BooleanField(
        default=False,
        help_text="Enable ShipFinance integration. When on, the member's "
                  "CorpScore tier affects their interest rate, insurance "
                  "premium, and eligibility for finance/rentals.",
    )

    # Minimum score to be eligible for finance at all. 0 = no minimum.
    shipfinance_min_score_finance = models.PositiveIntegerField(
        default=0,
        help_text="Members below this score cannot finance ships. 0 = no minimum.",
    )
    # Minimum score to be eligible for rentals. 0 = no minimum.
    shipfinance_min_score_rent = models.PositiveIntegerField(
        default=0,
        help_text="Members below this score cannot rent ships. 0 = no minimum.",
    )

    # Interest rate adjustments per tier (in percentage points, added to the
    # base rate from ShipFinance's offer config). Negative = discount.
    shipfinance_rate_adj_subprime = models.DecimalField(
        max_digits=5, decimal_places=2, default=5.00,
        help_text="Interest rate adjustment for Subprime (e.g. +5% added to base).",
    )
    shipfinance_rate_adj_fair = models.DecimalField(
        max_digits=5, decimal_places=2, default=2.00,
        help_text="Interest rate adjustment for Fair Weather Pilot.",
    )
    shipfinance_rate_adj_prime = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        help_text="Interest rate adjustment for Prime Member (baseline).",
    )
    shipfinance_rate_adj_elite = models.DecimalField(
        max_digits=5, decimal_places=2, default=-1.50,
        help_text="Interest rate adjustment for Elite Capsuleer (discount).",
    )
    shipfinance_rate_adj_blackcard = models.DecimalField(
        max_digits=5, decimal_places=2, default=-3.00,
        help_text="Interest rate adjustment for Black Card (best discount).",
    )

    # Insurance premium adjustments per tier (in percentage points, added to
    # the base premium rate). Risky borrowers pay more for insurance.
    shipfinance_insurance_adj_subprime = models.DecimalField(
        max_digits=5, decimal_places=2, default=3.00,
        help_text="Insurance premium adjustment for Subprime.",
    )
    shipfinance_insurance_adj_fair = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.00,
        help_text="Insurance premium adjustment for Fair Weather Pilot.",
    )
    shipfinance_insurance_adj_prime = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        help_text="Insurance premium adjustment for Prime Member (baseline).",
    )
    shipfinance_insurance_adj_elite = models.DecimalField(
        max_digits=5, decimal_places=2, default=-0.50,
        help_text="Insurance premium adjustment for Elite Capsuleer.",
    )
    shipfinance_insurance_adj_blackcard = models.DecimalField(
        max_digits=5, decimal_places=2, default=-1.00,
        help_text="Insurance premium adjustment for Black Card.",
    )

    last_recomputed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "CorpScore settings"
        verbose_name_plural = "CorpScore settings"

    def __str__(self):
        return self.name

    # --- helpers -----------------------------------------------------------
    def weights(self):
        return {
            "alliance_fat": self.weight_alliance_fat,
            "corp_fat": self.weight_corp_fat,
            "activity": self.weight_activity,
            "corptools": self.weight_corptools,
            "discord": self.weight_discord,
            "srp": self.weight_srp,
            "pvp": self.weight_pvp,
            "memberstatus": self.weight_memberstatus,
            "industrypool": self.weight_industrypool,
        }

    def decay_windows(self):
        return {
            "alliance_fat": self.decay_window_alliance_fat,
            "corp_fat": self.decay_window_corp_fat,
            "activity": self.decay_window_activity,
            "discord": self.decay_window_discord,
            "pvp": self.decay_window_pvp,
            "memberstatus": self.decay_window_memberstatus,
            "industrypool": self.decay_window_industrypool,
        }

    def tier_cutoffs(self):
        return {
            TIER_SUBPRIME: self.tier_subprime,
            TIER_FAIR: self.tier_fair,
            TIER_PRIME: self.tier_prime,
            TIER_ELITE: self.tier_elite,
            TIER_BLACKCARD: self.tier_blackcard,
        }

    def shipfinance_rate_adjustments(self):
        """Return per-tier interest rate adjustments (in percentage points)."""
        return {
            TIER_SUBPRIME: self.shipfinance_rate_adj_subprime,
            TIER_FAIR: self.shipfinance_rate_adj_fair,
            TIER_PRIME: self.shipfinance_rate_adj_prime,
            TIER_ELITE: self.shipfinance_rate_adj_elite,
            TIER_BLACKCARD: self.shipfinance_rate_adj_blackcard,
        }

    def shipfinance_insurance_adjustments(self):
        """Return per-tier insurance premium adjustments (in percentage points)."""
        return {
            TIER_SUBPRIME: self.shipfinance_insurance_adj_subprime,
            TIER_FAIR: self.shipfinance_insurance_adj_fair,
            TIER_PRIME: self.shipfinance_insurance_adj_prime,
            TIER_ELITE: self.shipfinance_insurance_adj_elite,
            TIER_BLACKCARD: self.shipfinance_insurance_adj_blackcard,
        }


class ScoreSnapshot(models.Model):
    """A single score computation for a user at a point in time.

    Snapshots are append-only - never updated. The history graph reads the
    trailing set of snapshots for a user.
    """

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="corpscore_snapshots",
    )
    score = models.PositiveIntegerField()
    tier = models.CharField(max_length=16, choices=TIER_CHOICES)
    computed_at = models.DateTimeField(auto_now_add=True)
    trigger = models.CharField(
        max_length=32,
        default="scheduled",
        help_text="What triggered this recompute: scheduled, import, manual, signal.",
    )

    class Meta:
        ordering = ["-computed_at"]
        indexes = [
            models.Index(fields=["user", "-computed_at"]),
        ]

    def __str__(self):
        return f"{self.user} {self.score} ({self.tier}) {self.computed_at:%Y-%m-%d}"


class ScoreComponentSnapshot(models.Model):
    """Per-component breakdown for a ScoreSnapshot.

    Stores the raw input value, the normalised 0-100 component score, the
    weight applied, and the points contributed. Lets the score card render
    the 'factors affecting your score' list.
    """

    snapshot = models.ForeignKey(
        ScoreSnapshot,
        on_delete=models.CASCADE,
        related_name="components",
    )
    component = models.CharField(max_length=32)
    raw_value = models.FloatField(default=0)
    raw_unit = models.CharField(max_length=32, blank=True, default="")
    normalised = models.FloatField(default=0)
    weight = models.PositiveIntegerField(default=0)
    points = models.FloatField(default=0)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-points"]

    def __str__(self):
        return f"{self.component}: {self.normalised}/100 ({self.points} pts)"


class HardInquiry(models.Model):
    """A 'hard pull' - logged when leadership views a member's full breakdown.

    Shown on the member's report and (optionally) penalises their score.
    """

    subject = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="corpscore_hard_inquiries_received",
    )
    pulled_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corpscore_hard_inquiries_made",
    )
    pulled_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-pulled_at"]
        indexes = [models.Index(fields=["subject", "-pulled_at"])]

    def __str__(self):
        return f"Hard pull on {self.subject} by {self.pulled_by} at {self.pulled_at:%Y-%m-%d}"


class Achievement(models.Model):
    """Achievement/badge definitions. Awarded by the scoring service based on
    component stats and tenure. Pure meme, high engagement.
    """

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=64, blank=True, default="fas fa-medal")
    # A simple JSON-ish rule spec consumed by services.evaluate_achievements.
    # Example: {"type": "min_component", "component": "alliance_fat", "value": 90}
    rule = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MemberAchievement(models.Model):
    """Achievement instances awarded to a user."""

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="corpscore_achievements",
    )
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "achievement")]
        ordering = ["-awarded_at"]

    def __str__(self):
        return f"{self.user} - {self.achievement.name}"


class ScoreEvent(models.Model):
    """A single meme 'statement' line item explaining a score delta.

    e.g. '+15 pts from 3 alliance fleets', '-8 pts from missed corp FAT minimum'.
    Rendered into the monthly statement view.
    """

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="corpscore_events",
    )
    delta = models.IntegerField(default=0)
    label = models.CharField(max_length=255)
    component = models.CharField(max_length=32, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.user} {sign}{self.delta} {self.label}"


class DiscordActivityDaily(models.Model):
    """Daily Discord activity per user, written by the activity_tracker cog.

    One row per Discord UID per date. The cog batches in-memory counters and
    flushes to this table periodically to avoid a DB write on every message.

    The discord adapter sums rows within the decay window to compute the
    member's Discord activity score.
    """

    discord_uid = models.BigIntegerField(db_index=True)
    date = models.DateField()
    message_count = models.PositiveIntegerField(default=0)
    voice_minutes = models.PositiveIntegerField(default=0)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("discord_uid", "date")]
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["discord_uid", "-date"]),
        ]
        verbose_name = "Discord activity (daily)"
        verbose_name_plural = "Discord activity (daily)"

    def __str__(self):
        return f"UID {self.discord_uid} {self.date}: {self.message_count} msgs, {self.voice_minutes}min voice"
