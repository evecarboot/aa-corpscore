"""SRP adapter - measures fleet discipline via SRP history.

Uses the allianceauth-srp plugin's SRPRequest data: a clean SRP history (no
denied/abused requests) scores well; denied requests or AWOX flags pull the
score down. Falls back to a neutral 50/100 if SRP isn't installed, so the
component neither helps nor hurts when there's no data.
"""

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult


class SrpAdapter(BaseAdapter):
    component = "srp"

    def available(self) -> bool:
        try:
            __import__("srp.models")
            return True
        except Exception:
            return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="SRP discipline")
        try:
            from srp.models import SrpUserRequest
        except Exception:
            # No SRP plugin: neutral baseline so this component is a no-op.
            result.normalised = 50.0
            result.note = "SRP plugin not installed"
            return result

        char_ids = _safe_char_ids(user)
        if not char_ids:
            result.normalised = 50.0
            result.note = "No characters linked"
            return result

        try:
            qs = SrpUserRequest.objects.filter(character__character_id__in=char_ids)
            total = qs.count()
            if total == 0:
                # No SRP history at all: neutral.
                result.normalised = 50.0
                result.note = "No SRP history"
                return result
            # Count statuses. Approved = good, Rejected/Denied = bad.
            approved = qs.filter(status="approved").count()
            rejected = qs.filter(status__in=["rejected", "denied"]).count()
            score = 50.0 + (approved / total) * 50.0 - (rejected / total) * 50.0
            result.raw_value = float(total)
            result.normalised = max(0.0, min(100.0, score))
            result.note = f"{approved} approved / {rejected} rejected of {total} SRP requests"
            return result
        except Exception:
            result.normalised = 50.0
            result.note = "SRP data unreadable"
            return result


def _safe_char_ids(user):
    try:
        from aa_corpscore.adapters.corp_fat import _user_character_ids
        return _user_character_ids(user)
    except Exception:
        return []
