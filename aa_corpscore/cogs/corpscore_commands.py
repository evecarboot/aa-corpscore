"""Discord slash commands for aa-corpscore.

Provides slash commands for members and leadership to check CorpScores from
Discord. Install by adding this cog to your aa-discordbot config in ``local.py``::

    DISCORD_BOT_COGS = [
        ...default cogs...,
        "aa_corpscore.cogs.corpscore_commands",
    ]

Commands (all slash commands):
    /corpscore          - Show your own CorpScore (ephemeral, only you see it)
    /corpscore member   - Leadership: hard-pull another member's score (requires
                          the view_breakdown permission in Auth)
    /corpscore board    - Show the top 10 corp members by score (requires
                          view_leaderboard permission)

The meme factor is huge: "checking your credit score from Discord."
"""

import logging

from discord.colour import Color
from discord.embeds import Embed
from discord.ext import commands

from aadiscordbot.app_settings import get_all_servers
from aadiscordbot.cogs.utils.decorators import sender_has_any_perm

logger = logging.getLogger(__name__)

# Tier colors for embeds (matching the web UI).
TIER_COLORS = {
    "subprime": Color.red(),
    "fair": Color.orange(),
    "prime": Color.blue(),
    "elite": Color.green(),
    "blackcard": Color.purple(),
}


def _resolve_user_from_discord(discord_user_id):
    """Resolve a Discord UID to an Auth User via DiscordUser."""
    try:
        from allianceauth.services.modules.discord.models import DiscordUser
        du = DiscordUser.objects.filter(uid=discord_user_id).first()
        if du:
            return du.user
    except Exception:
        pass
    return None


def _build_score_embed(user, snapshot, tier_label, tier_color):
    """Build a Discord embed for a member's score."""
    from aa_corpscore import services
    embed = Embed(title="CorpScore Report")
    embed.colour = tier_color

    try:
        main_char = user.profile.main_character
        name = str(main_char) if main_char else user.username
    except Exception:
        name = user.username

    embed.description = f"**{name}**"

    if snapshot is None:
        embed.description += "\n\nNo score on file. Scores are recomputed nightly."
        return embed

    embed.add_field(name="Score", value=f"**{snapshot.score}** / 850", inline=True)
    embed.add_field(name="Tier", value=tier_label, inline=True)
    embed.add_field(
        name="Last Updated",
        value=f"<t:{int(snapshot.computed_at.timestamp())}:R>",
        inline=True,
    )

    # Top 3 components.
    components = list(snapshot.components.all().order_by("-points")[:3])
    if components:
        comp_text = "\n".join(
            f"{'🟢' if c.normalised >= 70 else '🟡' if c.normalised >= 40 else '🔴'} "
            f"{c.component.replace('_', ' ').title()}: {c.normalised:.0f}/100"
            for c in components
        )
        embed.add_field(name="Top Factors", value=comp_text, inline=False)

    embed.set_footer(text="CorpScore - like a credit score, but for capsuleers")
    return embed


def _build_leaderboard_embed(entries):
    """Build a Discord embed for the top-10 leaderboard."""
    embed = Embed(title="CorpScore Leaderboard", colour=Color.gold())
    embed.description = "Top 10 capsuleers by CorpScore"

    if not entries:
        embed.description = "No scores computed yet."
        return embed

    medals = ["🥇", "🥈", "🥉"] + [f"`{i}.`" for i in range(4, 11)]
    lines = []
    for i, snap in enumerate(entries[:10]):
        try:
            name = str(snap.user.profile.main_character) if snap.user.profile.main_character else snap.user.username
        except Exception:
            name = snap.user.username
        from aa_corpscore import services
        tier_label = services.tier_label(snap.tier)
        medal = medals[i] if i < len(medals) else f"`{i+1}.`"
        lines.append(f"{medal} **{snap.score}** - {name} ({tier_label})")

    embed.add_field(name="Top 10", value="\n".join(lines), inline=False)
    embed.set_footer(text="CorpScore - like a credit score, but for capsuleers")
    return embed


class CorpScoreCommands(commands.Cog):
    """CorpScore slash commands for Discord."""

    def __init__(self, bot):
        self.bot = bot

    corpscore = commands.SlashCommandGroup(
        "corpscore",
        "Check CorpScores - like a credit score, but for capsuleers",
        guild_ids=get_all_servers(),
    )

    @corpscore.command(name="me", description="Check your own CorpScore")
    async def score_me(self, ctx):
        """Show the requesting user's own score (ephemeral)."""
        await ctx.defer(ephemeral=True)

        from aa_corpscore import services
        user = _resolve_user_from_discord(ctx.author.id)
        if user is None:
            return await ctx.respond(
                "Your Discord account isn't linked to Auth. "
                "Link it at the Auth site first.",
                ephemeral=True,
            )

        snapshot = services.latest_snapshot(user)
        tier = snapshot.tier if snapshot else "subprime"
        tier_label = services.tier_label(tier)
        tier_color = TIER_COLORS.get(tier, Color.greyple())
        embed = _build_score_embed(user, snapshot, tier_label, tier_color)
        return await ctx.respond(embed=embed, ephemeral=True)

    @corpscore.command(name="member", description="Check another member's CorpScore (leadership)")
    @sender_has_any_perm(["aa_corpscore.view_breakdown"])
    async def score_member(self, ctx, member: commands.Member):
        """Leadership: hard-pull another member's score. Logs a hard inquiry."""
        await ctx.defer(ephemeral=True)

        from aa_corpscore import services
        target_user = _resolve_user_from_discord(member.id)
        if target_user is None:
            return await ctx.respond(
                f"{member.mention}'s Discord account isn't linked to Auth.",
                ephemeral=True,
            )

        # Log the hard inquiry (meme: this affects their score).
        requester = _resolve_user_from_discord(ctx.author.id)
        if requester:
            services.log_hard_inquiry(
                subject=target_user,
                pulled_by=requester,
                reason=f"Discord slash command by {ctx.author.name}",
            )

        snapshot = services.latest_snapshot(target_user)
        tier = snapshot.tier if snapshot else "subprime"
        tier_label = services.tier_label(tier)
        tier_color = TIER_COLORS.get(tier, Color.greyple())
        embed = _build_score_embed(target_user, snapshot, tier_label, tier_color)
        embed.description += "\n\n⚠️ **Hard pull logged** - this inquiry may affect their score."
        return await ctx.respond(embed=embed, ephemeral=True)

    @corpscore.command(name="board", description="Show the top 10 CorpScore leaderboard")
    @sender_has_any_perm(["aa_corpscore.view_leaderboard"])
    async def scoreboard(self, ctx):
        """Show the top 10 leaderboard."""
        await ctx.defer(ephemeral=True)

        from aa_corpscore import services
        entries = services.leaderboard(limit=10)
        embed = _build_leaderboard_embed(entries)
        return await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    """Cog entry point - called by aa-discordbot on load."""
    bot.add_cog(CorpScoreCommands(bot))
    logger.info("CorpScore slash commands cog loaded")
