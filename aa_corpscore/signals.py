"""Signal handlers for AA CorpScore.

Listens to signals from external plugins (AA-FatImporter, AFAT, CorpTools,
MemberStatus) and triggers an async score recompute for the affected user.
This makes scores reactive instead of waiting for the nightly Celery beat.

All handlers are guarded so missing plugins don't cause import errors.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _trigger_recompute(user, trigger="signal"):
    """Trigger an async score recompute for a user, best-effort."""
    if user is None:
        return
    try:
        from aa_corpscore.tasks import recompute_user_score
        recompute_user_score.delay(user.pk, trigger=trigger)
    except Exception:
        # Celery not available or task not registered - skip silently.
        # The nightly beat will catch up.
        logger.debug("Could not trigger async recompute for user %s", user, exc_info=True)


def _user_from_character(character):
    """Resolve an EveCharacter to its auth User, if linked."""
    try:
        profile = character.userprofile
        return profile.user if hasattr(profile, "user") else None
    except Exception:
        pass
    try:
        from allianceauth.authentication.models import UserProfile
        profile = UserProfile.objects.filter(main_character=character).first()
        return profile.user if profile else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# AA-FatImporter: FatImportRecord / FatImportMemberResult
# ---------------------------------------------------------------------------

def _setup_fatimporter_signals():
    try:
        from fatimporter.models import FatImportRecord, FatImportMemberResult
    except Exception:
        return

    @receiver(post_save, sender=FatImportRecord)
    def on_fatimport_record_saved(sender, instance, **kwargs):
        """When a new FAT import completes, recompute all affected users."""
        try:
            from aa_corpscore.tasks import recompute_all_scores
            recompute_all_scores.delay(trigger="fatimport")
        except Exception:
            pass

    @receiver(post_save, sender=FatImportMemberResult)
    def on_fatimport_member_saved(sender, instance, **kwargs):
        """When a member's FAT result is saved, recompute that user."""
        user = _user_from_character_name(getattr(instance, "character_name", None))
        _trigger_recompute(user, trigger="fatimport_member")


def _user_from_character_name(name):
    """Resolve a character name to a user via EveCharacter."""
    if not name:
        return None
    try:
        from allianceauth.eveonline.models import EveCharacter
        char = EveCharacter.objects.filter(character_name=name).first()
        if char:
            return _user_from_character(char)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# AFAT: Fat model
# ---------------------------------------------------------------------------

def _setup_afat_signals():
    try:
        from afat.models import Fat
    except Exception:
        return

    @receiver(post_save, sender=Fat)
    def on_afat_saved(sender, instance, **kwargs):
        """When a FAT is recorded, recompute the affected user."""
        char = getattr(instance, "character", None)
        if char:
            user = _user_from_character(char)
            _trigger_recompute(user, trigger="afat")


# ---------------------------------------------------------------------------
# CorpTools: CharacterAudit
# ---------------------------------------------------------------------------

def _setup_corptools_signals():
    try:
        from corptools.models import CharacterAudit
    except Exception:
        return

    @receiver(post_save, sender=CharacterAudit)
    def on_corptools_audit_saved(sender, instance, **kwargs):
        """When a character audit refreshes, recompute the user."""
        char = getattr(instance, "character", None)
        if char:
            user = _user_from_character(char)
            _trigger_recompute(user, trigger="corptools_audit")


# ---------------------------------------------------------------------------
# MemberStatus: InactivityPing (member becomes inactive/active)
# ---------------------------------------------------------------------------

def _setup_memberstatus_signals():
    try:
        from memberstatus.models import InactivityPing
    except Exception:
        return

    @receiver(post_save, sender=InactivityPing)
    def on_memberstatus_ping(sender, instance, **kwargs):
        """When a member is pinged for inactivity, recompute their score."""
        user = getattr(instance, "user", None)
        _trigger_recompute(user, trigger="memberstatus_ping")


# ---------------------------------------------------------------------------
# IndustryPool: JobRequest (member completes industry jobs)
# ---------------------------------------------------------------------------

def _setup_industrypool_signals():
    try:
        from industrypool.models import JobRequest
    except Exception:
        return

    @receiver(post_save, sender=JobRequest)
    def on_industrypool_job_saved(sender, instance, **kwargs):
        """When a job request status changes, recompute the builder's score."""
        # Only care about delivered/completed jobs - those are the ones that
        # represent actual industry contribution.
        if instance.status not in ("delivered", "completed"):
            return
        user = instance.builder
        _trigger_recompute(user, trigger="industrypool_job")


# ---------------------------------------------------------------------------
# Register all signal handlers on module import.
# ---------------------------------------------------------------------------

_setup_fatimporter_signals()
_setup_afat_signals()
_setup_corptools_signals()
_setup_memberstatus_signals()
_setup_industrypool_signals()
