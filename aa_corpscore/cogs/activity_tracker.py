"""Discord activity tracking cog for aa-corpscore.

Listens to ``on_message`` and ``on_voice_state_update`` events and persists
per-user daily activity to the ``DiscordActivityDaily`` model. The discord
adapter reads from that model to compute the Discord score component.

**Installation:** add this cog to your aa-discordbot config in ``local.py``::

    DISCORD_BOT_COGS = [
        ...default cogs...,
        "aa_corpscore.cogs.activity_tracker",
    ]

**Design notes:**

- Message counts are accumulated in an in-memory dict and flushed to the DB
  every 5 minutes (via ``discord.ext.tasks``) to avoid a DB write per message.
- Voice minutes are computed on channel leave/disconnect from the recorded
  join time.
- Bot messages and DMs are ignored.
- Data is keyed by Discord UID; the adapter maps auth users to UIDs via
  ``DiscordUser``.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

from discord.ext import commands, tasks

from aa_corpscore.models import DiscordActivityDaily

logger = logging.getLogger(__name__)

# How often to flush in-memory message counters to the DB.
FLUSH_INTERVAL_MINUTES = 5


class ActivityTracker(commands.Cog):
    """Tracks Discord message and voice activity for CorpScore."""

    def __init__(self, bot):
        self.bot = bot
        # In-memory message counters: {discord_uid: {date_str: count}}
        self._message_buffer = defaultdict(lambda: defaultdict(int))
        # Voice channel join tracking: {discord_uid: datetime}
        self._voice_join_times = {}
        self.flush_buffer.start()

    def cog_unload(self):
        self.flush_buffer.cancel()
        # Final flush on unload so no data is lost.
        self._flush()

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        """Count non-bot messages in guild channels."""
        if message.author.bot:
            return
        if message.guild is None:
            return  # DMs don't count
        uid = message.author.id
        today = date.today().isoformat()
        self._message_buffer[uid][today] += 1

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track voice channel join/leave and compute minutes."""
        if member.bot:
            return

        uid = member.id
        now = _now()

        # User joined a voice channel.
        if before.channel is None and after.channel is not None:
            self._voice_join_times[uid] = now
            return

        # User left or moved channels.
        if before.channel is not None and after.channel is None:
            join_time = self._voice_join_times.pop(uid, None)
            if join_time:
                self._record_voice_minutes(uid, join_time, now)

        # User moved between channels - don't interrupt the timer.
        # (before.channel != after.channel but both not None: just update
        # the tracked channel, keep the original join time.)

    # ------------------------------------------------------------------
    # Background flush
    # ------------------------------------------------------------------

    @tasks.loop(minutes=FLUSH_INTERVAL_MINUTES)
    async def flush_buffer(self):
        """Flush in-memory message counters to the DB."""
        self._flush()

    @flush_buffer.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # DB writes
    # ------------------------------------------------------------------

    def _flush(self):
        """Write buffered message counts to DiscordActivityDaily."""
        if not self._message_buffer:
            return
        # Swap out the buffer so we don't block the event loop long.
        buffer = self._message_buffer
        self._message_buffer = defaultdict(lambda: defaultdict(int))

        from django.db import transaction

        with transaction.atomic():
            for uid, dates in buffer.items():
                for date_str, count in dates.items():
                    if count <= 0:
                        continue
                    day = date.fromisoformat(date_str)
                    obj, created = DiscordActivityDaily.objects.get_or_create(
                        discord_uid=uid,
                        date=day,
                        defaults={"message_count": count, "last_seen": _now()},
                    )
                    if not created:
                        obj.message_count += count
                        obj.last_seen = _now()
                        obj.save(update_fields=["message_count", "last_seen"])

    def _record_voice_minutes(self, uid, join_time, leave_time):
        """Compute voice minutes from join/leave times and write to DB."""
        if leave_time is None:
            return
        delta = leave_time - join_time
        minutes = max(0, int(delta.total_seconds() // 60))
        if minutes <= 0:
            return
        day = join_time.date()
        obj, created = DiscordActivityDaily.objects.get_or_create(
            discord_uid=uid,
            date=day,
            defaults={"voice_minutes": minutes},
        )
        if not created:
            obj.voice_minutes += minutes
            obj.save(update_fields=["voice_minutes"])


def _now():
    from django.utils import timezone
    return timezone.now()


def setup(bot):
    """Cog entry point - called by aa-discordbot on load."""
    bot.add_cog(ActivityTracker(bot))
    logger.info("CorpScore activity tracker cog loaded")
