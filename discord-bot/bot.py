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

from fwa_lookup import FwaLookupError, SCRAPERAPI_TIMEOUT, lookup_fwa_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fwa-bot")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

COOLDOWN_SECONDS = 10.0
LOOKUP_TIMEOUT_SECONDS = SCRAPERAPI_TIMEOUT + 5

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def run_lookup_in_thread(raw_tag: str):
    """lookup_fwa_status does blocking network I/O; run it off the event loop."""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lookup_fwa_status, raw_tag),
        timeout=LOOKUP_TIMEOUT_SECONDS,
    )


def make_sender(reply_fn):
    """Build a `send(**kwargs)` closure around a reply function (ctx.reply /
    interaction.followup.send) that knows how to send either an embed or
    plain text content."""

    async def send(**kwargs):
        if "embed" in kwargs:
            await reply_fn(embed=kwargs["embed"])
        else:
            await reply_fn(kwargs.get("content", ""))

    return send


def build_embed(result) -> discord.Embed:
    tag_link = f"[#{result.tag}]({result.source_url})"

    if not result.found:
        embed = discord.Embed(
            title=f"Player #{result.tag} not found",
            description="⚠️ No matching player was found on ChocolateClash for that tag.",
            color=discord.Color.orange(),
            url=result.source_url,
        )
        embed.add_field(name="🏷️ Tag", value=tag_link, inline=True)
        embed.add_field(name="🔗 Source", value=f"[View page]({result.source_url})", inline=True)
        embed.set_footer(text="Data from ChocolateClash (FWA)")
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
    embed.add_field(name="🏷️ Tag", value=tag_link, inline=True)
    if result.player_name:
        embed.add_field(name="👤 Name", value=result.player_name, inline=True)
    embed.add_field(name="FWA Ban Status", value=status_value, inline=False)
    embed.add_field(name="🔗 Source", value=f"[View on ChocolateClash]({result.source_url})", inline=False)
    embed.set_footer(text="Data from ChocolateClash (FWA)")
    return embed


async def handle_fwacheck(send, playertag: str) -> None:
    try:
        result = await run_lookup_in_thread(playertag)
    except ValueError as exc:
        await send(content=f"⚠️ {exc}. Example: `#9GQCYLYRC` or `9GQCYLYRC`.")
        return
    except asyncio.TimeoutError:
        logger.warning("Lookup timed out for %s", playertag)
        await send(content="⚠️ That lookup took too long. Please try again later.")
        return
    except FwaLookupError as exc:
        logger.warning("Lookup failed for %s: %s", playertag, exc)
        await send(content=f"⚠️ Couldn't complete the lookup right now: {exc} Please try again later.")
        return
    except Exception:
        logger.exception("Unexpected error looking up %s", playertag)
        await send(content="⚠️ Something went wrong while checking that player. Please try again later.")
        return

    embed = build_embed(result)
    await send(embed=embed)


@bot.command(name="fwacheck")
@commands.cooldown(rate=1, per=COOLDOWN_SECONDS, type=commands.BucketType.user)
async def fwacheck_prefix(ctx: commands.Context, playertag: str = None):
    if not playertag:
        await ctx.reply("Usage: `!fwacheck <playertag>` — e.g. `!fwacheck #9GQCYLYRC`")
        return

    send = make_sender(ctx.reply)

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


@bot.tree.command(name="fwacheck", description="Check if a Clash of Clans player is FWA banned")
@app_commands.describe(playertag="Clash of Clans player tag, e.g. #9GQCYLYRC")
@app_commands.checks.cooldown(rate=1, per=COOLDOWN_SECONDS)
async def fwacheck_slash(interaction: discord.Interaction, playertag: str):
    await interaction.response.defer()

    send = make_sender(interaction.followup.send)

    await handle_fwacheck(send, playertag)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Slow down! Try again in {error.retry_after:.0f}s."
    else:
        logger.exception("Unhandled app command error", exc_info=error)
        message = "⚠️ Something went wrong running that command."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


_synced = False


@bot.event
async def on_ready():
    global _synced
    logger.info("Logged in as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
    if _synced:
        return
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s)", len(synced))
        _synced = True
    except Exception:
        logger.exception("Failed to sync slash commands")


def main():
    if not TOKEN:
        logger.error(
            "DISCORD_BOT_TOKEN is not set. Add it to Replit Secrets before starting the bot."
        )
        sys.exit(1)
    if not os.environ.get("SCRAPERAPI_KEY"):
        logger.warning(
            "SCRAPERAPI_KEY not set — Cloudflare-blocked lookups will fail without the "
            "final fallback tier."
        )
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
