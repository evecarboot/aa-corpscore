"""ShipFinance integration API for aa-corpscore.

Public interface that [aa-shipfinance](https://github.com/evecarboot/aa-shipfinance)
calls to adjust financing terms based on the member's CorpScore tier. Like
real-life credit scores affecting loan terms: subprime borrowers pay higher
interest, Black Card members get preferential rates, below-threshold members
are denied entirely.

**Usage from ShipFinance:**

    from aa_corpscore.shipfinance import get_finance_terms, can_rent

    # When a member tries to finance a ship:
    terms = get_finance_terms(user, base_interest_rate=10, base_insurance_premium=5)
    if not terms.eligible:
        show_error(terms.ineligible_reason)
    else:
        use terms.adjusted_interest_rate and terms.adjusted_insurance_premium

    # When a member tries to rent:
    allowed, reason = can_rent(user)
    if not allowed:
        show_error(reason)

All functions degrade gracefully if CorpScore isn't installed or the
integration is disabled - they return the base rates unchanged and eligibility
as True, so ShipFinance works standalone without CorpScore.
"""

from dataclasses import dataclass
from decimal import Decimal

from aa_corpscore import services
from aa_corpscore.models import (
    SCORE_MAX,
    SCORE_MIN,
    ScoreSettings,
    TIER_BLACKCARD,
    TIER_ELITE,
    TIER_FAIR,
    TIER_PRIME,
    TIER_SUBPRIME,
)


@dataclass
class FinanceTerms:
    """Adjusted finance terms for a member based on their CorpScore."""

    eligible: bool
    ineligible_reason: str
    score: int
    tier: str
    tier_label: str
    base_interest_rate: Decimal
    adjusted_interest_rate: Decimal
    rate_adjustment: Decimal
    base_insurance_premium: Decimal
    adjusted_insurance_premium: Decimal
    insurance_adjustment: Decimal


def shipfinance_available() -> bool:
    """Return True if the ShipFinance integration is enabled in CorpScore settings."""
    try:
        settings = ScoreSettings.objects.first()
        return settings is not None and settings.shipfinance_enabled
    except Exception:
        return False


def _get_settings() -> ScoreSettings:
    return ScoreSettings.objects.first() or ScoreSettings.objects.create(name="main")


def _get_user_score_tier(user):
    """Return (score, tier) for a user, or (None, None) if no snapshot exists."""
    snapshot = services.latest_snapshot(user)
    if snapshot is None:
        return None, None
    return snapshot.score, snapshot.tier


def can_finance(user) -> tuple:
    """Check if a member is eligible to finance ships based on their CorpScore.

    Returns (eligible: bool, reason: str).
    If the integration is disabled or CorpScore has no score for the user,
    returns (True, "") so ShipFinance works standalone.
    """
    if not shipfinance_available():
        return True, ""

    settings = _get_settings()
    score, tier = _get_user_score_tier(user)

    if score is None:
        # No score computed yet - don't block finance, let ShipScore decide.
        return True, ""

    min_score = settings.shipfinance_min_score_finance
    if min_score > 0 and score < min_score:
        return False, (
            f"CorpScore {score} is below the minimum {min_score} required "
            f"for ship finance. Improve your corp activity to raise your score."
        )

    return True, ""


def can_rent(user) -> tuple:
    """Check if a member is eligible to rent ships based on their CorpScore.

    Returns (eligible: bool, reason: str).
    If the integration is disabled or no score exists, returns (True, "").
    """
    if not shipfinance_available():
        return True, ""

    settings = _get_settings()
    score, tier = _get_user_score_tier(user)

    if score is None:
        return True, ""

    min_score = settings.shipfinance_min_score_rent
    if min_score > 0 and score < min_score:
        return False, (
            f"CorpScore {score} is below the minimum {min_score} required "
            f"for ship rentals. Improve your corp activity to raise your score."
        )

    return True, ""


def get_rate_adjustment(user) -> Decimal:
    """Return the interest rate adjustment (in percentage points) for a user.

    Positive = premium (subprime pays more), negative = discount (Black Card
    pays less), zero = baseline. Returns Decimal(0) if integration is disabled
    or no score exists.
    """
    if not shipfinance_available():
        return Decimal("0")

    settings = _get_settings()
    score, tier = _get_user_score_tier(user)

    if tier is None:
        return Decimal("0")

    adjustments = settings.shipfinance_rate_adjustments()
    return adjustments.get(tier, Decimal("0"))


def get_insurance_adjustment(user) -> Decimal:
    """Return the insurance premium adjustment (in percentage points) for a user.

    Returns Decimal(0) if integration is disabled or no score exists.
    """
    if not shipfinance_available():
        return Decimal("0")

    settings = _get_settings()
    score, tier = _get_user_score_tier(user)

    if tier is None:
        return Decimal("0")

    adjustments = settings.shipfinance_insurance_adjustments()
    return adjustments.get(tier, Decimal("0"))


def get_finance_terms(
    user,
    base_interest_rate: Decimal = Decimal("10"),
    base_insurance_premium: Decimal = Decimal("5"),
) -> FinanceTerms:
    """Get the full adjusted finance terms for a member.

    This is the main entry point for ShipFinance. Pass the base interest rate
    and insurance premium from the admin-configured offer, and get back the
    adjusted rates based on the member's CorpScore tier.

    If the integration is disabled or no score exists, returns the base rates
    unchanged with eligible=True.
    """
    base_interest_rate = Decimal(str(base_interest_rate))
    base_insurance_premium = Decimal(str(base_insurance_premium))

    if not shipfinance_available():
        return FinanceTerms(
            eligible=True,
            ineligible_reason="",
            score=0,
            tier="",
            tier_label="",
            base_interest_rate=base_interest_rate,
            adjusted_interest_rate=base_interest_rate,
            rate_adjustment=Decimal("0"),
            base_insurance_premium=base_insurance_premium,
            adjusted_insurance_premium=base_insurance_premium,
            insurance_adjustment=Decimal("0"),
        )

    settings = _get_settings()
    score, tier = _get_user_score_tier(user)

    if score is None or tier is None:
        return FinanceTerms(
            eligible=True,
            ineligible_reason="",
            score=0,
            tier="",
            tier_label="No score yet",
            base_interest_rate=base_interest_rate,
            adjusted_interest_rate=base_interest_rate,
            rate_adjustment=Decimal("0"),
            base_insurance_premium=base_insurance_premium,
            adjusted_insurance_premium=base_insurance_premium,
            insurance_adjustment=Decimal("0"),
        )

    # Check eligibility.
    eligible, reason = can_finance(user)

    # Compute rate adjustments.
    rate_adj = get_rate_adjustment(user)
    insurance_adj = get_insurance_adjustment(user)

    adjusted_rate = base_interest_rate + rate_adj
    adjusted_insurance = base_insurance_premium + insurance_adj

    # Rates can't go below zero.
    if adjusted_rate < 0:
        adjusted_rate = Decimal("0")
    if adjusted_insurance < 0:
        adjusted_insurance = Decimal("0")

    return FinanceTerms(
        eligible=eligible,
        ineligible_reason=reason,
        score=score,
        tier=tier,
        tier_label=services.tier_label(tier),
        base_interest_rate=base_interest_rate,
        adjusted_interest_rate=adjusted_rate,
        rate_adjustment=rate_adj,
        base_insurance_premium=base_insurance_premium,
        adjusted_insurance_premium=adjusted_insurance,
        insurance_adjustment=insurance_adj,
    )
