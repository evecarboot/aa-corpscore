"""Discord adapter - measures Discord engagement via the activity_tracker cog.

Reads from the ``DiscordActivityDaily`` model (populated by the
``aa_corpscore.cogs.activity_tracker`` cog) to compute a Discord activity
score. Blends three sub-metrics:

- **Message activity** (50%): total messages in the decay window, normalised
  against a soft cap (500 messages = 100/100).
- **Voice activity** (30%): total voice minutes in the window, normalised
  against a soft cap (300 minutes = 100/100).
- **Recency** (20%): days since last_seen, full marks if seen today,
  decays to 0 over the decay window.

If the activity_tracker cog is not installed (no DiscordActivityDaily rows
exist for the user), falls back to checking whether the user has Discord
linked at all via ``DiscordUser`` - linked but no data gets a neutral
baseline, unlinked gets 0.
"""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from aa_corpscore.adapters.base import BaseAdapter, ComponentResult
from aa_corpscore.models import DiscordActivityDaily

# Soft caps for normalisation.
MESSAGE_SOFT_CAP = 500.0   # 500 messages in window = 100/100
VOICE_SOFT_CAP = 300.0     # 300 voice minutes in window = 100/100


class DiscordAdapter(BaseAdapter):
    component = "discord"

    def available(self) -> bool:
        """Available if either the aa-discordbot package or the core discord
        service is installed (so we can at least check if users are linked)."""
        for mod in ("aadiscordbot", "discord"):
            try:
                __import__(f"{mod}.models")
                return True
            except Exception:
                continue
        # Also available if we have activity data even without the bot package
        # (edge case: bot was uninstalled but historical data remains).
        return DiscordActivityDaily.objects.exists()

    def collect(self, user, settings) -> ComponentResult:
        result = ComponentResult(component=self.component, raw_unit="Discord activity (window)")
        window_days = settings.decay_windows().get(self.component, 30)
        cutoff = timezone.now() - timedelta(days=window_days)
        cutoff_date = cutoff.date()

        discord_uid = self._get_discord_uid(user)

        if discord_uid is None:
            result.normalised = 0.0
            result.note = "Discord not linked"
            return result

        # Query daily activity rows within the decay window.
        rows = DiscordActivityDaily.objects.filter(
            discord_uid=discord_uid,
            date__gte=cutoff_date,
        )
        total_messages = rows.aggregate(s=Sum("message_count"))["s"] or 0
        total_voice = rows.aggregate(s=Sum("voice_minutes"))["s"] or 0
        last_seen = None
        latest_row = rows.order_by("-last_seen").first()
        if latest_row and latest_row.last_seen:
            last_seen = latest_row.last_seen

        if total_messages == 0 and total_voice == 0 and last_seen is None:
            # Linked but no activity data (cog not installed or no activity).
            result.raw_value = 0
            result.normalised = 40.0  # neutral baseline for being linked
            result.note = "Discord linked, no activity data (install activity_tracker cog)"
            return result

        # Sub-scores.
        message_score = min(100.0, (total_messages / MESSAGE_SOFT_CAP) * 100.0)
        voice_score = min(100.0, (total_voice / VOICE_SOFT_CAP) * 100.0)

        if last_seen:
            days_since = max(0, (timezone.now() - last_seen).days)
            recency_score = max(0.0, 1.0 - (days_since / max(1, window_days))) * 100.0
        else:
            recency_score = 0.0

        # Blend: 50% messages, 30% voice, 20% recency.
        result.raw_value = float(total_messages + total_voice)
        result.normalised = (message_score * 0.5) + (voice_score * 0.3) + (recency_score * 0.2)
        result.note = (
            f"{total_messages} msgs, {total_voice}min voice in {window_days}d"
            + (f" | last seen {last_seen:%Y-%m-%d}" if last_seen else " | last seen unknown")
        )
        return result

    def _get_discord_uid(self, user):
        """Resolve the user's Discord UID via DiscordUser."""
        for mod in ("aadiscordbot", "discord"):
            try:
                m = __import__(f"{mod}.models", fromlist=["DiscordUser"])
                DiscordUser = m.DiscordUser
                du = DiscordUser.objects.filter(user=user).first()
                if du:
                    return du.uid
            except Exception:
                continue
        return None
