"""PvP adapter - pulls kill/loss data from the zKillboard Statistics API.

Uses https://zkillboard.com/api/stats/characterID/{id}/ which returns total
kills, losses, ISK destroyed/lost, and per-month breakdowns in a single call.

Scoring blends two sub-metrics:
- **Activity** (70%): kills + losses within the decay window. Shows the member
  is actually PvPing. Soft cap at 50 engagements/window = 100.
- **Efficiency** (30%): ISK destroyed / (ISK destroyed + ISK lost) within the
  window. The meme "credit utilisation" factor - losing more than you kill is
  like maxing out your credit card.

This adapter is **off by default**. It only reports `available()` as True when
the admin has enabled it in ScoreSettings (`zkill_enabled = True`). This avoids
hitting the zKillboard API for corps that don't want PvP in their scores.

API etiquette:
- Results are cached per-character for the recompute interval (default 24h).
- A descriptive User-Agent is sent with every request.
- One API call per character per recompute cycle (cached across users in the
  same cycle if they share characters, which is rare but possible).
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult
from aa_corpscore.adapters.corp_fat import _user_character_ids

logger = logging.getLogger(__name__)

ZKILL_STATS_URL = "https://zkillboard.com/api/stats/characterID/{char_id}/"
ZKILL_CACHE_KEY = "aa_corpscore:zkill:stats:{char_id}"
ZKILL_CACHE_TIMEOUT = 86400  # 24 hours
ZKILL_USER_AGENT = "aa-corpscore/0.1 (Alliance Auth CorpScore plugin)"

# Soft cap for activity normalisation: 50 kills+losses in window = 100/100.
ACTIVITY_SOFT_CAP = 50.0


class PvpAdapter(BaseAdapter):
    component = "pvp"

    def available(self) -> bool:
        """Available only if the admin has enabled zKillboard integration."""
        try:
            from aa_corpscore.models import ScoreSettings
            settings = ScoreSettings.objects.first()
            if not settings:
                return False
            return bool(getattr(settings, "zkill_enabled", False))
        except Exception:
            return False

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="PvP engagements (window)")

        char_ids = _user_character_ids(user)
        if not char_ids:
            result.note = "No characters linked"
            result.normalised = 0.0
            return result

        window_days = settings.decay_windows().get(self.component, 90)
        cutoff = timezone.now() - timedelta(days=window_days)

        total_kills = 0
        total_losses = 0
        isk_destroyed = 0.0
        isk_lost = 0.0

        for char_id in char_ids:
            stats = self._fetch_stats(char_id)
            if not stats:
                continue
            k, l, id_, il_ = self._extract_window(stats, cutoff)
            total_kills += k
            total_losses += l
            isk_destroyed += id_
            isk_lost += il_

        if total_kills == 0 and total_losses == 0:
            result.raw_value = 0
            result.normalised = 0.0
            result.note = f"No PvP activity in last {window_days}d"
            return result

        # Activity sub-score: kills + losses, normalised against soft cap.
        engagements = total_kills + total_losses
        activity_score = min(100.0, (engagements / ACTIVITY_SOFT_CAP) * 100.0)

        # Efficiency sub-score: ISK ratio. 50/50 = 50, 100/0 = 100, 0/100 = 0.
        total_isk = isk_destroyed + isk_lost
        if total_isk > 0:
            efficiency_score = (isk_destroyed / total_isk) * 100.0
        else:
            # No ISK data but has engagements - give neutral efficiency.
            efficiency_score = 50.0

        # Blend: 70% activity, 30% efficiency.
        result.raw_value = float(engagements)
        result.normalised = (activity_score * 0.7) + (efficiency_score * 0.3)
        result.note = (
            f"{total_kills} kills / {total_losses} losses in {window_days}d "
            f"| ISK eff: {result.normalised * 0.3 / 100 * 100:.0f}%"
        )
        return result

    def _fetch_stats(self, char_id):
        """Fetch zKillboard stats for a character, with caching."""
        cache_key = ZKILL_CACHE_KEY.format(char_id=char_id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            import requests
        except ImportError:
            logger.warning("requests not installed - zKillboard adapter disabled")
            return None

        url = ZKILL_STATS_URL.format(char_id=char_id)
        try:
            resp = requests.get(url, headers={"User-Agent": ZKILL_USER_AGENT}, timeout=15)
            if resp.status_code != 200:
                logger.warning("zKillboard API returned %s for char %s", resp.status_code, char_id)
                return None
            data = resp.json()
        except Exception as exc:
            logger.warning("zKillboard API error for char %s: %s", char_id, exc)
            return None

        cache.set(cache_key, data, ZKILL_CACHE_TIMEOUT)
        return data

    def _extract_window(self, stats, cutoff):
        """Extract kills, losses, ISK destroyed, ISK lost within the window.

        zKillboard stats returns a `months` array with entries like:
        {"month": "202608", "kills": 10, "losses": 2, "iskDestroyed": ..., "iskLost": ...}
        We sum entries whose month is >= the cutoff month.
        """
        kills = losses = 0
        isk_destroyed = isk_lost = 0.0

        cutoff_int = int(cutoff.strftime("%Y%m"))
        months = stats.get("months", [])
        for entry in months:
            month_str = str(entry.get("month", ""))
            try:
                month_int = int(month_str)
            except ValueError:
                continue
            if month_int >= cutoff_int:
                kills += int(entry.get("kills", 0))
                losses += int(entry.get("losses", 0))
                isk_destroyed += float(entry.get("iskDestroyed", 0) or 0)
                isk_lost += float(entry.get("iskLost", 0) or 0)

        return kills, losses, isk_destroyed, isk_lost
