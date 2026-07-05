"""
FWA Ban Check Discord bot.

Commands:
    !fwacheck <playertag>   (prefix command)
    /fwacheck <playertag>   (slash command)

Looks up a Clash of Clans player tag on cc.fwafarm.com (ChocolateClash /
FWA Farm) and reports whether the player is on the FWA ban list.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

from fwa_lookup import FwaLookupError, lookup_fwa_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fwa-bot")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

COOLDOWN_SECONDS = 10.0

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def run_lookup_in_thread(raw_tag: str):
    """lookup_fwa_status does blocking network I/O; run it off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lookup_fwa_status, raw_tag)


def build_embed(result) -> discord.Embed:
    if not result.found:
        embed = discord.Embed(
            title=f"Player #{result.tag} not found",
            description="No matching player was found on ChocolateClash for that tag.",
            color=discord.Color.orange(),
            url=result.source_url,
        )
        embed.add_field(name="Tag", value=f"#{result.tag}", inline=True)
        embed.add_field(name="Source", value=f"[View page]({result.source_url})", inline=True)
        return embed

    if result.banned:
        color = discord.Color.red()
        status_value = "🚫 Banned"
        if result.reason:
            status_value += f"\n{result.reason}"
    else:
        color = discord.Color.green()
        status_value = "✅ Not banned"

    embed = discord.Embed(
        title=result.player_name or f"Player #{result.tag}",
        color=color,
        url=result.source_url,
    )
    embed.add_field(name="Tag", value=f"#{result.tag}", inline=True)
    if result.player_name:
        embed.add_field(name="Name", value=result.player_name, inline=True)
    embed.add_field(name="FWA Ban Status", value=status_value, inline=False)
    embed.add_field(name="Source", value=f"[View on ChocolateClash]({result.source_url})", inline=False)
    embed.set_footer(text="Data from cc.fwafarm.com")
    return embed


async def handle_fwacheck(send, playertag: str) -> None:
    try:
        result = await run_lookup_in_thread(playertag)
    except ValueError as exc:
        await send(f"⚠️ {exc}. Example: `#9GQCYLYRC` or `9GQCYLYRC`.")
        return
    except FwaLookupError as exc:
        logger.warning("Lookup failed for %s: %s", playertag, exc)
        await send(f"⚠️ Couldn't complete the lookup right now: {exc} Please try again later.")
        return
    except Exception:
        logger.exception("Unexpected error looking up %s", playertag)
        await send("⚠️ Something went wrong while checking that player. Please try again later.")
        return

    embed = build_embed(result)
    await send(embed=embed)


@bot.command(name="fwacheck")
@commands.cooldown(rate=1, per=COOLDOWN_SECONDS, type=commands.BucketType.user)
async def fwacheck_prefix(ctx: commands.Context, playertag: str = None):
    if not playertag:
        await ctx.reply("Usage: `!fwacheck <playertag>` — e.g. `!fwacheck #9GQCYLYRC`")
        return

    async def send(**kwargs):
        if "embed" in kwargs:
            await ctx.reply(embed=kwargs["embed"])
        else:
            await ctx.reply(kwargs.get("content", ""))

    async with ctx.typing():
        await handle_fwacheck(send, playertag)


@fwacheck_prefix.error
async def fwacheck_prefix_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(
            f"⏳ Slow down! Try again in {error.retry_after:.0f}s."
        )
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!fwacheck <playertag>` — e.g. `!fwacheck #9GQCYLYRC`")
    else:
        logger.exception("Unhandled command error", exc_info=error)
        await ctx.reply("⚠️ Something went wrong running that command.")


_slash_cooldowns: dict[int, float] = {}


@bot.tree.command(name="fwacheck", description="Check if a Clash of Clans player is FWA banned")
@app_commands.describe(playertag="Clash of Clans player tag, e.g. #9GQCYLYRC")
async def fwacheck_slash(interaction: discord.Interaction, playertag: str):
    loop = asyncio.get_running_loop()
    now = loop.time()
    user_id = interaction.user.id
    last_used = _slash_cooldowns.get(user_id)
    if last_used is not None and (now - last_used) < COOLDOWN_SECONDS:
        remaining = COOLDOWN_SECONDS - (now - last_used)
        await interaction.response.send_message(
            f"⏳ Slow down! Try again in {remaining:.0f}s.", ephemeral=True
        )
        return
    _slash_cooldowns[user_id] = now

    await interaction.response.defer()

    async def send(**kwargs):
        if "embed" in kwargs:
            await interaction.followup.send(embed=kwargs["embed"])
        else:
            await interaction.followup.send(kwargs.get("content", ""))

    await handle_fwacheck(send, playertag)


@bot.event
async def on_ready():
    logger.info("Logged in as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s)", len(synced))
    except Exception:
        logger.exception("Failed to sync slash commands")


def main():
    if not TOKEN:
        logger.error(
            "DISCORD_BOT_TOKEN is not set. Add it to Replit Secrets before starting the bot."
        )
        sys.exit(1)
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
