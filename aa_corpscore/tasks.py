"""Celery tasks for AA CorpScore."""

from celery import shared_task


@shared_task
def recompute_all_scores(trigger="scheduled"):
    """Recompute every user's score. Called by the nightly beat schedule,
    after an AA-FatImporter import (via signal), or manually from admin."""
    from aa_corpscore.services import recompute_all_users
    return recompute_all_users(trigger=trigger)


@shared_task
def recompute_user_score(user_id, trigger="signal"):
    """Recompute a single user's score. Useful after a FAT import or audit update."""
    from django.contrib.auth import get_user_model
    from aa_corpscore.services import compute_score_for_user
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None
    return compute_score_for_user(user, trigger=trigger).pk
