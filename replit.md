# FWA Ban Check Discord Bot

A Discord bot that looks up a Clash of Clans player tag on ChocolateClash (cc.fwafarm.com) and reports whether the player is on the FWA ban list.

## Run & Operate

- The bot runs as the "FWA Discord Bot" workflow: `python3 discord-bot/bot.py`
- `discord-bot/fwa_lookup.py` — standalone lookup/parsing logic, testable via `python3 discord-bot/fwa_lookup.py <tag>`
- `discord-bot/bot.py` — discord.py bot wiring up `!fwacheck` and `/fwacheck`
- Required secret: `DISCORD_BOT_TOKEN` — Discord bot token (Replit Secrets)
- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000, unrelated scaffold artifact)
- `pnpm run typecheck` — full typecheck across all JS/TS packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

_Populate as you build — short repo map plus pointers to the source-of-truth file for DB schema, API contracts, theme files, etc._

## Architecture decisions

- The bot lives in `discord-bot/` (plain Python, not a pnpm workspace artifact) since it's a background worker with no web preview.
- Lookup logic (`fwa_lookup.py`) is separated from Discord wiring (`bot.py`) so the HTTP/parsing logic can be tested standalone without a Discord connection.
- Fetch strategy: try plain `requests` first, detect a Cloudflare challenge page (403/503 or "Just a moment"-style markers), then retry with `cloudscraper`. If both are blocked, the command replies with a friendly "try again later" message instead of crashing.
- HTML parsing is layered: look for structured elements (labelled table rows, elements with name/status/ban classes) first, then fall back to scanning visible page text for ban/not-found keywords, since the site's markup isn't guaranteed to stay stable.

## Product

- `!fwacheck <tag>` and `/fwacheck <tag>` — look up a Clash of Clans player tag on ChocolateClash (cc.fwafarm.com) and reply with an embed showing player name, FWA ban status, and a link to the source page.
- 1 lookup per user per 10 seconds cooldown on both the prefix and slash command.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- cc.fwafarm.com is protected by a Cloudflare managed challenge that plain `requests` AND `cloudscraper` both failed to bypass during testing (confirmed 2026-07-05) — real-world lookups may frequently hit the "couldn't bypass Cloudflare" error path. This is expected/handled gracefully, not a bug.
- The bot requires the `message_content` privileged intent for the `!fwacheck` prefix command to read message text — this must be enabled in the Discord Developer Portal under Bot > Privileged Gateway Intents, or the prefix command won't receive arguments (the slash command doesn't need it).

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
