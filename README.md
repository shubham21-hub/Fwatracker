# FWA Ban Check Discord Bot

A Discord bot that checks whether a Clash of Clans player is on the FWA ban
list by looking up their player tag on
[ChocolateClash](https://cc.fwafarm.com) (cc.fwafarm.com).

## Commands

- `!fwacheck <tag>` — prefix command
- `/fwacheck <tag>` — slash command

Both reply with an embed showing the player's name, FWA ban status, and a
clickable link back to the source page on ChocolateClash. Each user is
limited to one lookup every 10 seconds.

## How it works

1. The bot normalizes the given Clash of Clans player tag.
2. It fetches the player's member page on `cc.fwafarm.com`, trying in order:
   - a plain HTTP request,
   - a `cloudscraper` request (to get past basic Cloudflare challenges),
<<<<<<< HEAD
   - a ScraperAPI request with JS rendering enabled (Cloudflare bypass
     fallback),
   - a ScrapingAnt request (backup used if ScraperAPI is unavailable, errors,
     or its credits/quota run out).
=======
   - a ScraperAPI request with JS rendering enabled (further Cloudflare
     bypass fallback).
>>>>>>> bd515d01c99f82a70355c6e859cfe1c30bfacbfd
3. It parses the page for the player's name and ban status and replies with
   a formatted Discord embed (green = not banned, red = banned).

If all fetch strategies are blocked, the bot replies with a friendly
"try again later" message instead of crashing.

## Setup

### Requirements

- Python 3.11+
- A Discord bot application/token (with the **Message Content** privileged
  intent enabled, required for the `!fwacheck` prefix command)
- A [ScraperAPI](https://www.scraperapi.com/) account/API key (used as a
  fallback when Cloudflare blocks the direct/`cloudscraper` requests)
<<<<<<< HEAD
- A [ScrapingAnt](https://app.scrapingant.com/register) account/API key
  (free tier, used as a backup if ScraperAPI is unavailable or its
  credits/quota run out)
=======
>>>>>>> bd515d01c99f82a70355c6e859cfe1c30bfacbfd

### Install dependencies

```bash
pip install -r discord-bot/requirements.txt
```

### Environment variables

Set these as environment variables / Replit Secrets — never commit them to
the repo:

<<<<<<< HEAD
| Variable              | Description                                                        |
| --------------------- | ------------------------------------------------------------------ |
| `DISCORD_BOT_TOKEN`   | Discord bot token from the Discord Developer Portal                |
| `SCRAPERAPI_KEY`      | ScraperAPI API key, used as a Cloudflare-bypass fallback            |
| `SCRAPINGANT_API_KEY` | ScrapingAnt API key, used as a backup if ScraperAPI is unavailable or out of credits |
=======
| Variable            | Description                                                        |
| ------------------- | ------------------------------------------------------------------ |
| `DISCORD_BOT_TOKEN` | Discord bot token from the Discord Developer Portal                |
| `SCRAPERAPI_KEY`    | ScraperAPI API key, used as a Cloudflare-bypass fallback            |
>>>>>>> bd515d01c99f82a70355c6e859cfe1c30bfacbfd

### Run the bot

```bash
python3 discord-bot/bot.py
```

On Replit, this is wired up as the "FWA Discord Bot" workflow.

### Testing the lookup logic standalone

The scraping/parsing logic can be tested without connecting to Discord:

```bash
python3 discord-bot/fwa_lookup.py <playertag>
```

## Project structure

```
discord-bot/
├── bot.py            # Discord command wiring, embeds, cooldowns
├── fwa_lookup.py      # Standalone fetch/parse logic for the FWA lookup
└── requirements.txt   # Python dependencies
```

## Known limitations

- `cc.fwafarm.com` is protected by a Cloudflare managed challenge. Even with
<<<<<<< HEAD
  the `cloudscraper`, ScraperAPI, and ScrapingAnt fallbacks, some lookups may
  still fail — this is handled gracefully with a "try again later" reply
  rather than a crash.
- ScraperAPI's rendering mode can occasionally require a higher-tier
  (premium/ultra-premium) proxy plan for this specific domain; on lower-tier
  plans this fallback may not always succeed.
- In testing, ScrapingAnt's free-tier browser rendering (with and without
  residential/US proxy settings) got stuck on Cloudflare's "Just a moment..."
  challenge page for this domain and did not successfully bypass it — unlike
  ScraperAPI, which did succeed. It's still wired in as a best-effort backup
  (e.g. useful if ScraperAPI's account itself is unavailable), but it is not
  a guaranteed working fallback for this specific site.
=======
  the `cloudscraper` and ScraperAPI fallbacks, some lookups may still fail —
  this is handled gracefully with a "try again later" reply rather than a
  crash.
- ScraperAPI's rendering mode can occasionally require a higher-tier
  (premium/ultra-premium) proxy plan for this specific domain; on lower-tier
  plans this fallback may not always succeed.
>>>>>>> bd515d01c99f82a70355c6e859cfe1c30bfacbfd
