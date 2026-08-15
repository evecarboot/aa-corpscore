"""Scoring service for AA CorpScore.

Computes a FICO-style 300-850 score per user by:
1. Running each available adapter to collect raw inputs and a 0-100 component score.
2. Blending component scores by their configured weights into a 0-100 blended score.
3. Mapping the blended score onto the 300-850 range.
4. Applying the hard-inquiry penalty (meme accuracy).
5. Persisting a ScoreSnapshot + ScoreComponentSnapshot rows.
6. Awarding achievements and emitting ScoreEvent rows for the meme statement.

Also exposes helpers for tier resolution, group gating, and recompute triggers.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from aa_corpscore.adapters import get_adapter
from aa_corpscore.models import (
    DEFAULT_TIER_CUTOFFS,
    MemberAchievement,
    SCORE_MAX,
    SCORE_MIN,
    ScoreComponentSnapshot,
    ScoreEvent,
    ScoreSettings,
    ScoreSnapshot,
    TIER_BLACKCARD,
    TIER_ELITE,
    TIER_FAIR,
    TIER_PRIME,
    TIER_SUBPRIME,
)

# ---------------------------------------------------------------------------
# Tier helpers
# ---------------------------------------------------------------------------

def tier_for_score(score, settings=None):
    """Return the tier key for a given score using settings cutoffs."""
    cutoffs = (settings.tier_cutoffs() if settings else DEFAULT_TIER_CUTOFFS)
    if score >= cutoffs[TIER_BLACKCARD]:
        return TIER_BLACKCARD
    if score >= cutoffs[TIER_ELITE]:
        return TIER_ELITE
    if score >= cutoffs[TIER_PRIME]:
        return TIER_PRIME
    if score >= cutoffs[TIER_FAIR]:
        return TIER_FAIR
    return TIER_SUBPRIME


def tier_label(tier):
    return dict([(k, v) for k, v in [
        (TIER_SUBPRIME, "Subprime Capsuleer"),
        (TIER_FAIR, "Fair Weather Pilot"),
        (TIER_PRIME, "Prime Member"),
        (TIER_ELITE, "Elite Capsuleer"),
        (TIER_BLACKCARD, "Black Card / Concord-Verified"),
    ]]).get(tier, tier)


def tier_color(tier):
    return {
        TIER_SUBPRIME: "#e74c3c",
        TIER_FAIR: "#f39c12",
        TIER_PRIME: "#3498db",
        TIER_ELITE: "#2ecc71",
        TIER_BLACKCARD: "#9b59b6",
    }.get(tier, "#95a5a6")


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def get_settings():
    return ScoreSettings.objects.first() or ScoreSettings.objects.create(name="main")


@transaction.atomic
def compute_score_for_user(user, trigger="scheduled"):
    """Compute and persist a score snapshot for `user`. Returns the ScoreSnapshot."""
    settings = get_settings()
    weights = settings.weights()
    components = []
    total_weight = 0
    blended = 0.0

    for component_key, weight in weights.items():
        if weight <= 0:
            continue
        adapter = get_adapter(component_key)
        if adapter is None:
            continue
        try:
            if not adapter.available():
                continue
            result = adapter.collect(user, settings)
        except Exception as exc:  # never let one adapter break the whole recompute
            from aa_corpscore.adapters.base import ComponentResult
            result = ComponentResult(
                component=component_key,
                note=f"Adapter error: {exc}",
                normalised=50.0,  # neutral so a broken adapter doesn't tank the score
            )
        components.append((result, weight))
        blended += result.normalised * weight
        total_weight += weight

    if total_weight == 0:
        blended_score = 0.0
    else:
        blended_score = blended / total_weight  # 0-100

    # Map 0-100 blended onto 300-850.
    score = int(round(SCORE_MIN + (blended_score / 100.0) * (SCORE_MAX - SCORE_MIN)))

    # Hard-inquiry penalty (meme).
    penalty = _hard_inquiry_penalty(user, settings)
    score = max(SCORE_MIN, min(SCORE_MAX, score - penalty))

    tier = tier_for_score(score, settings)

    snapshot = ScoreSnapshot.objects.create(
        user=user,
        score=score,
        tier=tier,
        trigger=trigger,
    )

    for result, weight in components:
        points = (result.normalised * weight / total_weight) if total_weight else 0
        ScoreComponentSnapshot.objects.create(
            snapshot=snapshot,
            component=result.component,
            raw_value=result.raw_value,
            raw_unit=result.raw_unit,
            normalised=result.normalised,
            weight=weight,
            points=points,
            note=result.note,
        )

    # Achievements + events (best-effort, never break the snapshot).
    try:
        evaluate_achievements(user, snapshot, components)
    except Exception:
        pass

    # Score events for the meme statement (best-effort).
    try:
        emit_score_events(user, snapshot, components, total_weight)
    except Exception:
        pass

    # Group gating.
    try:
        apply_group_gating(user, tier, settings)
    except Exception:
        pass

    # Invalidate the cached latest snapshot for this user.
    _invalidate_snapshot_cache(user.pk)

    return snapshot


def _hard_inquiry_penalty(user, settings):
    if not settings.log_hard_inquiries or settings.hard_inquiry_penalty == 0:
        return 0
    from aa_corpscore.models import HardInquiry
    cutoff = timezone.now() - timedelta(days=settings.hard_inquiry_penalty_window_days)
    count = HardInquiry.objects.filter(subject=user, pulled_at__gte=cutoff).count()
    return min(settings.hard_inquiry_penalty_max, count * settings.hard_inquiry_penalty)


# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------

def evaluate_achievements(user, snapshot, components):
    """Award achievements based on the just-computed snapshot."""
    from aa_corpscore.models import Achievement

    component_map = {r.component: r for r, _ in components}
    by_component = {k: v.normalised for k, v in component_map.items()}

    rules = [
        ("on_time", "On Time Every Time", "90 days with no missed FAT minimum", "fas fa-clock",
         {"type": "min_component", "component": "alliance_fat", "value": 80}),
        ("strat_ops", "Strategic Operator", "Strong strategic FAT participation", "fas fa-crosshairs",
         {"type": "min_component", "component": "corp_fat", "value": 75}),
        ("loyal", "Loyal Customer", "Score never below 600 this snapshot", "fas fa-shield-alt",
         {"type": "min_score", "value": 600}),
        ("audited", "Audit-Ready", "CorpTools audit fully fresh", "fas fa-clipboard-check",
         {"type": "min_component", "component": "corptools", "value": 80}),
        ("vocal", "Vocal Customer", "Active on Discord", "fas fa-comments",
         {"type": "min_component", "component": "discord", "value": 70}),
        ("blackcard", "Black Card Holder", "Reached Black Card tier", "fas fa-crown",
         {"type": "tier", "value": TIER_BLACKCARD}),
        ("hard_victim", "Hard Inquiry Victim", "5+ hard pulls this month", "fas fa-search",
         {"type": "hard_inquiries", "value": 5}),
    ]

    for slug, name, desc, icon, rule in rules:
        Achievement.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "description": desc, "icon": icon, "rule": rule},
        )

    for slug, name, desc, icon, rule in rules:
        if _rule_matches(rule, user, snapshot, by_component):
            ach = Achievement.objects.get(slug=slug)
            MemberAchievement.objects.get_or_create(user=user, achievement=ach)


def _rule_matches(rule, user, snapshot, by_component):
    rtype = rule.get("type")
    if rtype == "min_component":
        return by_component.get(rule["component"], 0) >= rule["value"]
    if rtype == "min_score":
        return snapshot.score >= rule["value"]
    if rtype == "tier":
        return snapshot.tier == rule["value"]
    if rtype == "hard_inquiries":
        from aa_corpscore.models import HardInquiry
        cutoff = timezone.now() - timedelta(days=30)
        return HardInquiry.objects.filter(subject=user, pulled_at__gte=cutoff).count() >= rule["value"]
    return False


# ---------------------------------------------------------------------------
# Score events (meme statement line items)
# ---------------------------------------------------------------------------

# Human-readable labels for each component, used in the statement.
_COMPONENT_LABELS = {
    "alliance_fat": "Alliance FAT participation",
    "corp_fat": "Corp FAT participation",
    "activity": "General activity",
    "corptools": "Character audit status",
    "discord": "Discord engagement",
    "srp": "SRP record",
    "pvp": "PvP combat (zKillboard)",
    "memberstatus": "Member activity status",
    "industrypool": "Industry pool contribution",
}


def emit_score_events(user, snapshot, components, total_weight):
    """Create ScoreEvent rows by comparing this snapshot to the previous one.

    Generates meme-style statement line items like:
        +12 pts from Alliance FAT participation
        -5 pts from Discord engagement
        +3 pts from Character audit status

    Also emits tier-change events ("Promoted to Elite Capsuleer!") and a
    hard-inquiry event if any inquiries were logged since the last snapshot.
    """
    previous = ScoreSnapshot.objects.filter(user=user).exclude(pk=snapshot.pk).first()

    if previous is None:
        # First-ever snapshot: emit one event per component as a baseline.
        for result, weight in components:
            if total_weight == 0:
                continue
            points = int(round(result.normalised * weight / total_weight))
            if points == 0:
                continue
            label = _COMPONENT_LABELS.get(result.component, result.component)
            ScoreEvent.objects.create(
                user=user,
                delta=points,
                label=f"Initial {label.lower()}",
                component=result.component,
            )
        return

    # Compare component scores to the previous snapshot.
    prev_components = {
        c.component: c for c in previous.components.all()
    }
    for result, weight in components:
        if total_weight == 0:
            continue
        prev = prev_components.get(result.component)
        prev_normalised = prev.normalised if prev else 0.0
        delta_normalised = result.normalised - prev_normalised
        if abs(delta_normalised) < 1.0:
            continue  # ignore noise
        # Convert normalised delta to score points.
        points = int(round(delta_normalised * weight / total_weight))
        if points == 0:
            continue
        label = _COMPONENT_LABELS.get(result.component, result.component)
        sign = "Improved" if points > 0 else "Declined"
        ScoreEvent.objects.create(
            user=user,
            delta=points,
            label=f"{sign} {label.lower()}",
            component=result.component,
        )

    # Tier change event.
    if previous.tier != snapshot.tier:
        if snapshot.score > previous.score:
            ScoreEvent.objects.create(
                user=user,
                delta=0,
                label=f"Promoted to {tier_label(snapshot.tier)}!",
                component="",
            )
        else:
            ScoreEvent.objects.create(
                user=user,
                delta=0,
                label=f"Demoted to {tier_label(snapshot.tier)}",
                component="",
            )

    # Hard inquiry event (if any new inquiries since last snapshot).
    from aa_corpscore.models import HardInquiry
    inquiry_cutoff = previous.computed_at
    new_inquiries = HardInquiry.objects.filter(
        subject=user, pulled_at__gte=inquiry_cutoff,
    ).count()
    if new_inquiries > 0:
        penalty = _hard_inquiry_penalty(user, get_settings())
        ScoreEvent.objects.create(
            user=user,
            delta=-penalty,
            label=f"{new_inquiries} hard pull(s) on your report",
            component="hard_inquiry",
        )


# ---------------------------------------------------------------------------
# Group gating
# ---------------------------------------------------------------------------

def apply_group_gating(user, tier, settings):
    if not settings.group_gating_enabled:
        return
    if settings.elite_group:
        if tier in (TIER_ELITE, TIER_BLACKCARD):
            user.groups.add(settings.elite_group)
        else:
            user.groups.remove(settings.elite_group)
    if settings.subprime_group:
        if tier == TIER_SUBPRIME:
            user.groups.add(settings.subprime_group)
        else:
            user.groups.remove(settings.subprime_group)


# ---------------------------------------------------------------------------
# Hard inquiries
# ---------------------------------------------------------------------------

def log_hard_inquiry(subject, pulled_by, reason=""):
    """Record a hard pull. Called when leadership views a member's breakdown."""
    from aa_corpscore.models import HardInquiry
    settings = get_settings()
    if not settings.log_hard_inquiries:
        return None
    return HardInquiry.objects.create(subject=subject, pulled_by=pulled_by, reason=reason)


# ---------------------------------------------------------------------------
# Recompute orchestration
# ---------------------------------------------------------------------------

def recompute_all_users(trigger="scheduled"):
    """Recompute scores for every user. Returns count.

    Uses a bulk-optimised path: pre-fetches all users in one query and
    processes them in a single transaction per batch, rather than opening
    a transaction per user. Adapter queries still run per-user (each adapter
    may have different query patterns), but snapshot/component/event writes
    are batched.
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction
    User = get_user_model()

    count = 0
    batch_size = 100
    user_qs = User.objects.all().values_list("pk", flat=True).iterator(chunk_size=batch_size)

    batch = []
    for user_pk in user_qs:
        batch.append(user_pk)
        if len(batch) >= batch_size:
            count += _recompute_batch(batch, trigger)
            batch = []
    if batch:
        count += _recompute_batch(batch, trigger)

    settings = get_settings()
    settings.last_recomputed_at = timezone.now()
    settings.save(update_fields=["last_recomputed_at"])
    return count


def _recompute_batch(user_pks, trigger):
    """Recompute scores for a batch of user PKs. Returns count of successes."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    count = 0
    for pk in user_pks:
        try:
            user = User.objects.get(pk=pk)
            compute_score_for_user(user, trigger=trigger)
            count += 1
        except Exception:
            continue
    return count


def latest_snapshot(user):
    """Return the user's latest snapshot, cached for 60 seconds.

    The cache is keyed by user PK and invalidated in compute_score_for_user()
    when a new snapshot is written.
    """
    from django.core.cache import cache
    cache_key = f"aa_corpscore:latest_snapshot:{user.pk}"
    snap = cache.get(cache_key)
    if snap is not None:
        return snap
    snap = ScoreSnapshot.objects.filter(user=user).first()
    cache.set(cache_key, snap, 60)
    return snap


def _invalidate_snapshot_cache(user_pk):
    """Clear the cached latest snapshot for a user (call after recompute)."""
    from django.core.cache import cache
    cache.delete(f"aa_corpscore:latest_snapshot:{user_pk}")


def snapshot_history(user, limit=30):
    return list(ScoreSnapshot.objects.filter(user=user).order_by("-computed_at")[:limit])


def leaderboard(limit=100):
    """Return the latest snapshot per user, sorted by score desc."""
    qs = ScoreSnapshot.objects.raw(
        """
        SELECT s.* FROM aa_corpscore_scoresnapshot s
        JOIN (
            SELECT user_id, MAX(computed_at) AS max_at
            FROM aa_corpscore_scoresnapshot
            GROUP BY user_id
        ) m ON s.user_id = m.user_id AND s.computed_at = m.max_at
        ORDER BY s.score DESC
        LIMIT %s
        """,
        [limit],
    )
    return list(qs)


def score_distribution():
    """Return a dict tier -> count for the leaderboard histogram."""
    dist = {TIER_SUBPRIME: 0, TIER_FAIR: 0, TIER_PRIME: 0, TIER_ELITE: 0, TIER_BLACKCARD: 0}
    for snap in leaderboard(limit=10000):
        dist[snap.tier] = dist.get(snap.tier, 0) + 1
    return dist


def what_if(user, overrides):
    """Run a hypothetical recompute without persisting. `overrides` is a dict
    of component_key -> normalised (0-100). Returns (score, tier)."""
    settings = get_settings()
    weights = settings.weights()
    blended = 0.0
    total_weight = 0
    for key, weight in weights.items():
        if weight <= 0:
            continue
        val = overrides.get(key)
        if val is None:
            adapter = get_adapter(key)
            if adapter is None or not adapter.available():
                continue
            try:
                result = adapter.collect(user, settings)
                val = result.normalised
            except Exception:
                continue
        blended += val * weight
        total_weight += weight
    blended_score = blended / total_weight if total_weight else 0
    score = int(round(SCORE_MIN + (blended_score / 100.0) * (SCORE_MAX - SCORE_MIN)))
    return score, tier_for_score(score, settings)
