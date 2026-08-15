"""Corp FAT adapter - reads corp fleet FATs from AFAT.

AFAT (allianceauth/afat) stores per-character FAT entries in `afat.Fat`. We
count FATs for the user's characters within the configured decay window and
normalise against a soft cap.
"""

from datetime import timedelta

from django.utils import timezone

from aa_corpscore.adapters.alliance_fat import _main_character_name
from aa_corpscore.adapters.base import BaseAdapter, ComponentResult


class CorpFatAdapter(BaseAdapter):
    component = "corp_fat"

    def available(self) -> bool:
        try:
            from afat.models import Fat  # noqa: F401
            return True
        except Exception:
            return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="corp FATs (window)")
        try:
            from afat.models import Fat
        except Exception:
            return result

        char_ids = _user_character_ids(user)
        if not char_ids:
            result.note = "No characters linked"
            return result

        window_days = settings.decay_windows().get(self.component, 90)
        cutoff = timezone.now() - timedelta(days=window_days)
        count = Fat.objects.filter(
            character__eve_character_id__in=char_ids,
            fatlink__created_at__gte=cutoff,
        ).count()

        result.raw_value = float(count)
        cap = 30.0  # 30 corp FATs in window = 100
        result.normalised = min(100.0, (result.raw_value / cap) * 100.0)
        result.note = f"{count} corp FATs in last {window_days}d"
        return result


def _user_character_ids(user):
    """Return eve character IDs for all of the user's linked characters."""
    try:
        profile = user.profile
        chars = profile.characters.all() if hasattr(profile, "characters") else []
        if not chars and profile.main_character:
            chars = [profile.main_character]
        return [c.character_id for c in chars]
    except Exception:
        return []
