---
name: Cloudflare scraping limits
description: What to expect when a scraping target is behind a Cloudflare managed challenge, and how to handle it robustly.
---

Some sites (e.g. cc.fwafarm.com / ChocolateClash) sit behind a Cloudflare
"managed challenge" (the "Just a moment..." interstitial). During testing,
both plain `requests` and `cloudscraper` (with chrome/firefox browser
profiles, with/without delay) returned the challenge page (HTTP 403,
title "Just a moment...") — cloudscraper's JS-challenge solver does not
handle Cloudflare's newer managed-challenge/Turnstile flow.

**Why:** Cloudflare's managed challenge often requires actual browser
rendering (e.g. a headless browser with a real JS engine) or a paid
CAPTCHA-solving proxy service — `cloudscraper` alone is not sufficient
for every Cloudflare deployment.

**How to apply:** When asked to scrape a Cloudflare-protected site:
- Still implement the `requests` → `cloudscraper` fallback chain (it's cheap and works for older/lighter Cloudflare setups).
- Always detect the challenge page explicitly (status 403/503, or markers like "just a moment", "checking your browser", "cloudflare" in the HTML) and raise a distinct, catchable error.
- Design the calling code (bot command, API route, etc.) to fail gracefully with a "try again later" style message rather than assuming the bypass will succeed — don't crash or silently return wrong data.
- If the user needs guaranteed access, flag that a headless-browser solution (e.g. Playwright with stealth plugins) or a third-party unblocking API would be the next step beyond cloudscraper.

**ScraperAPI as a further fallback (cc.fwafarm.com, 2026-07-05):** plain `render=true` calls to ScraperAPI intermittently succeeded (200 with real HTML) and intermittently failed with a 500 telling you to add `premium=true`/`ultra_premium=true` for "protected domains" — and `ultra_premium=true` itself 403'd because the plan didn't include premium proxy pools. Treat ScraperAPI's success as non-deterministic per-request for Cloudflare-protected targets on a base plan; always keep the existing friendly-error fallback path rather than assuming ScraperAPI guarantees a bypass.
- `render=true` requests to ScraperAPI can take 50-60+ seconds even when they ultimately fail — a 30s timeout is too aggressive and causes spurious `ReadTimeout` failures; use 60-70s+ for render-mode requests.
