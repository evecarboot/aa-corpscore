"""Alliance FAT adapter - reads alliance FAT totals from AA-FatImporter.

AA-FatImporter stores per-import member rows in `FatImportMemberResult`. We take
the latest import's row for the user's main character name and use the total
FATs as the raw input. Decay is applied by the scoring service based on the
import recency (the import is a point-in-time snapshot, so we treat the import
date as the activity date).
"""

from datetime import timedelta

from django.utils import timezone

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult


class AllianceFatAdapter(BaseAdapter):
    component = "alliance_fat"

    def available(self) -> bool:
        try:
            from aa_fatimporter.models import FatImportMemberResult  # noqa: F401
            return True
        except Exception:
            return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="alliance FATs (90d)")
        try:
            from aa_fatimporter.models import FatImportRecord, FatImportMemberResult
        except Exception:
            return result

        main_name = _main_character_name(user)
        if not main_name:
            result.note = "No main character linked"
            return result

        latest = FatImportRecord.objects.order_by("-imported_at").first()
        if not latest:
            result.note = "No alliance FAT import on record"
            return result

        member = latest.member_results.filter(character_name__iexact=main_name).first()
        if not member:
            result.raw_value = 0
            result.note = f"{main_name} not in latest alliance import"
            return result

        result.raw_value = float(member.total_fats)
        # Normalise against a soft cap of 20 alliance FATs/90d = 100.
        # Below the corp's typical required minimum (10) scores poorly.
        cap = 20.0
        result.normalised = min(100.0, (result.raw_value / cap) * 100.0)
        result.note = f"{int(result.raw_value)} alliance FATs in latest import"
        return result


def _main_character_name(user) -> str:
    """Resolve the user's main character name via Alliance Auth's profile."""
    try:
        profile = user.profile
        return profile.main_character.character_name if profile.main_character else ""
    except Exception:
        return ""
