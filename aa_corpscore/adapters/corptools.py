"""CorpTools adapter - measures character-audit compliance.

CorpTools / MembersAudit tracks whether a user's characters are being kept
up-to-date (skill queues pulled, etc.). A user whose characters are all
successfully audited scores well; stale or untracked characters score poorly.

Tries `corptools` first, then `membersaudit` (the newer package name).
"""

from datetime import timedelta

from django.utils import timezone

from aa_corpscore.adapters.corp_fat import _user_character_ids
from aa_corpscore.adapters.base import BaseAdapter, ComponentResult


class CorpToolsAdapter(BaseAdapter):
    component = "corptools"

    def available(self) -> bool:
        for mod in ("corptools", "membersaudit"):
            try:
                __import__(f"{mod}.models")
                return True
            except Exception:
                continue
        return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="audit freshness")
        char_ids = _user_character_ids(user)
        if not char_ids:
            result.note = "No characters linked"
            return result

        # Try corptools first, then membersaudit.
        statuses = self._fetch_statuses(char_ids)
        if statuses is None:
            result.note = "CorpTools/MembersAudit not installed"
            return result

        if not statuses:
            result.normalised = 0.0
            result.note = "No audited characters"
            return result

        # Each character: 100 if last_update < 7d, decays to 0 over 30d.
        now = timezone.now()
        scores = []
        for last_update in statuses:
            if last_update is None:
                scores.append(0.0)
                continue
            age_days = max(0, (now - last_update).days)
            scores.append(max(0.0, 1.0 - (age_days / 30.0)) * 100.0)

        audited_count = sum(1 for s in statuses if s is not None)
        result.raw_value = audited_count / len(statuses) if statuses else 0.0
        result.normalised = sum(scores) / len(scores) if scores else 0.0
        fresh = sum(1 for s in scores if s >= 80)
        result.note = f"{fresh}/{len(statuses)} characters fresh (<7d since audit)"
        return result

    def _fetch_statuses(self, char_ids):
        """Return a list of last_update datetimes for the given char ids, or
        None if neither audit package is installed."""
        # corptools
        try:
            from corptools.models import CharacterAudit
            qs = CharacterAudit.objects.filter(character__character_id__in=char_ids)
            return list(qs.values_list("last_update", flat=True))
        except Exception:
            pass
        # membersaudit
        try:
            from membersaudit.models import Character  # noqa: F401
            from membersaudit.models import CharacterUpdateStatus
            qs = CharacterUpdateStatus.objects.filter(character__eve_character_id__in=char_ids)
            return list(qs.values_list("last_update", flat=True))
        except Exception:
            pass
        return None
