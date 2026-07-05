"""
Lookup logic for checking a Clash of Clans player's FWA ban status on
the ChocolateClash / FWA Farm website (cc.fwafarm.com).

This module is intentionally independent of discord.py so it can be
tested from the command line:

    python fwa_lookup.py 9GQCYLYRC
"""

from __future__ import annotations

import logging
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
except ImportError:  # pragma: no cover - cloudscraper should always be installed
    cloudscraper = None  # type: ignore[assignment]

logger = logging.getLogger("fwa-bot.lookup")

BASE_URL = "https://cc.fwafarm.com/cc_n/member.php"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 15

SCRAPERAPI_URL = "https://api.scraperapi.com/"
SCRAPERAPI_TIMEOUT = 70

TAG_RE = re.compile(r"^[A-Z0-9]{3,12}$")

CLOUDFLARE_MARKERS = (
    "just a moment",
    "checking your browser",
    "attention required",
    "cf-browser-verification",
    "cloudflare",
    "enable javascript and cookies to continue",
)


class FwaLookupError(Exception):
    """Raised when the lookup cannot be completed (site down, blocked, etc.)."""


@dataclass
class FwaLookupResult:
    tag: str
    source_url: str
    found: bool
    player_name: Optional[str] = None
    banned: Optional[bool] = None
    reason: Optional[str] = None


def normalize_tag(raw_tag: str) -> str:
    """Strip '#' and whitespace, uppercase. Raises ValueError if empty/invalid."""
    if raw_tag is None:
        raise ValueError("No tag provided")
    tag = raw_tag.strip().upper()
    if tag.startswith("#"):
        tag = tag[1:]
    tag = tag.strip()
    if not tag or not TAG_RE.match(tag):
        raise ValueError(f"'{raw_tag}' doesn't look like a valid Clash of Clans player tag")
    return tag


def _looks_like_cloudflare_challenge(html: str, status_code: int) -> bool:
    if status_code in (403, 503):
        return True
    lowered = html.lower()
    return any(marker in lowered for marker in CLOUDFLARE_MARKERS)


def _fetch_with_requests(url: str) -> tuple[int, str]:
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    return resp.status_code, resp.text


def _fetch_with_cloudscraper(url: str) -> tuple[int, str]:
    if cloudscraper is None:
        raise FwaLookupError("cloudscraper is not installed")
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    resp = scraper.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=REQUEST_TIMEOUT)
    return resp.status_code, resp.text


def _fetch_with_scraperapi(url: str) -> tuple[int, str]:
    api_key = os.environ.get("SCRAPERAPI_KEY")
    if not api_key:
        raise FwaLookupError("SCRAPERAPI_KEY is not configured")

    params = {
        "api_key": api_key,
        "url": url,
        "render": "true",
    }
    request_url = f"{SCRAPERAPI_URL}?{urllib.parse.urlencode(params)}"
    resp = requests.get(request_url, timeout=SCRAPERAPI_TIMEOUT)
    return resp.status_code, resp.text


def fetch_member_page(tag: str) -> str:
    """
    Fetch the member.php page for the given (already normalized) tag.

    Order of attempts:
      1. Plain `requests` with a browser User-Agent.
      2. `cloudscraper`, if (1) failed or returned a Cloudflare challenge page.
      3. ScraperAPI (with render=true), if (2) failed or returned a challenge
         page. Requires SCRAPERAPI_KEY to be set; skipped (with a warning)
         if it isn't.

    Raises FwaLookupError if all available attempts fail.
    """
    url = f"{BASE_URL}?tag={tag}"

    try:
        status_code, html = _fetch_with_requests(url)
    except requests.RequestException:
        status_code, html = 0, ""
        requests_ok = False
    else:
        requests_ok = True

    if requests_ok and not _looks_like_cloudflare_challenge(html, status_code):
        if status_code >= 500:
            raise FwaLookupError(f"Site returned server error {status_code}")
        return html

    # Fall back to cloudscraper
    try:
        status_code, html = _fetch_with_cloudscraper(url)
        cloudscraper_ok = True
    except Exception:  # noqa: BLE001 - cloudscraper can raise various errors
        logger.warning("cloudscraper fetch failed for tag %s", tag, exc_info=True)
        status_code, html = 0, ""
        cloudscraper_ok = False

    if cloudscraper_ok and not _looks_like_cloudflare_challenge(html, status_code):
        if status_code >= 400:
            raise FwaLookupError(f"Site returned error {status_code}")
        return html

    # Fall back to ScraperAPI
    if not os.environ.get("SCRAPERAPI_KEY"):
        logger.warning(
            "SCRAPERAPI_KEY is not set; skipping ScraperAPI fallback for tag %s", tag
        )
        raise FwaLookupError(
            "The FWA lookup site is behind a Cloudflare check that couldn't be bypassed."
        )

    try:
        status_code, html = _fetch_with_scraperapi(url)
    except requests.RequestException:
        logger.warning("ScraperAPI request failed for tag %s", tag, exc_info=True)
        raise FwaLookupError(
            "The FWA lookup site is behind a Cloudflare check that couldn't be bypassed."
        )

    if status_code >= 400:
        logger.warning(
            "ScraperAPI returned status %s for tag %s: %s", status_code, tag, html[:300]
        )
        raise FwaLookupError(
            "The FWA lookup site is behind a Cloudflare check that couldn't be bypassed."
        )

    if _looks_like_cloudflare_challenge(html, status_code):
        raise FwaLookupError(
            "The FWA lookup site is behind a Cloudflare check that couldn't be bypassed."
        )

    return html


_BAN_KEYWORDS = ("banned", "ban list", "blacklisted", "in fwa ban")
_NOT_FOUND_KEYWORDS = (
    "not found",
    "no member",
    "no results",
    "does not exist",
    "invalid tag",
    "no such player",
)


def parse_member_page(html: str, tag: str, source_url: str) -> FwaLookupResult:
    """
    Parse the member.php HTML for player name + ban status.

    The exact markup of cc.fwafarm.com can change, so this parser is
    deliberately layered:
      1. Look for common structured elements (tables, definition lists,
         elements with class/id hints like 'name', 'status', 'ban').
      2. Fall back to scanning the visible page text for ban/not-found
         keywords.
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(separator=" ", strip=True)
    lowered_text = page_text.lower()

    if not page_text or len(page_text) < 20:
        raise FwaLookupError("Received an empty page from the FWA lookup site.")

    if any(keyword in lowered_text for keyword in _NOT_FOUND_KEYWORDS):
        return FwaLookupResult(tag=tag, source_url=source_url, found=False)

    player_name = _extract_player_name(soup, page_text)

    banned = None
    reason = None

    ban_el = soup.find(
        lambda el: el.name in ("td", "span", "div", "li", "p", "b", "strong")
        and el.get("class")
        and any("ban" in c.lower() or "status" in c.lower() for c in el.get("class"))
    )
    if ban_el is not None:
        ban_text = ban_el.get_text(" ", strip=True)
        banned = "banned" in ban_text.lower() and "not banned" not in ban_text.lower()
        reason = ban_text if banned else None
    else:
        table_row_text = _find_labelled_row_text(soup, ("status", "ban", "banned"))
        if table_row_text is not None:
            banned = "banned" in table_row_text.lower() and "not banned" not in table_row_text.lower()
            reason = table_row_text if banned else None

    if banned is None:
        if "not banned" in lowered_text or "no ban" in lowered_text:
            banned = False
        elif any(keyword in lowered_text for keyword in _BAN_KEYWORDS):
            banned = True
            reason = _extract_snippet_around(page_text, "ban")
        else:
            banned = False

    if player_name is None and banned is False and not any(
        keyword in lowered_text for keyword in _BAN_KEYWORDS
    ) and "player" not in lowered_text and "clan" not in lowered_text:
        # Page doesn't look like a real member page at all.
        return FwaLookupResult(tag=tag, source_url=source_url, found=False)

    return FwaLookupResult(
        tag=tag,
        source_url=source_url,
        found=True,
        player_name=player_name,
        banned=banned,
        reason=reason,
    )


def _extract_player_name(soup: BeautifulSoup, page_text: str) -> Optional[str]:
    for tag_name in ("h1", "h2", "h3"):
        el = soup.find(tag_name)
        if el:
            text = el.get_text(" ", strip=True)
            if text and len(text) < 60:
                return text

    name_el = soup.find(
        lambda el: el.name in ("td", "span", "div")
        and el.get("class")
        and any("name" in c.lower() for c in el.get("class"))
    )
    if name_el:
        text = name_el.get_text(" ", strip=True)
        if text:
            return text

    row_text = _find_labelled_row_text(soup, ("name", "player"))
    if row_text:
        return row_text

    return None


def _find_labelled_row_text(soup: BeautifulSoup, labels: tuple[str, ...]) -> Optional[str]:
    """Look for table rows / definition-list pairs like 'Status: Banned'."""
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(" ", strip=True).lower()
            if any(lbl in label for lbl in labels):
                return cells[1].get_text(" ", strip=True)

    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True).lower()
        if any(lbl in label for lbl in labels):
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(" ", strip=True)

    return None


def _extract_snippet_around(text: str, keyword: str, radius: int = 60) -> str:
    lowered = text.lower()
    idx = lowered.find(keyword)
    if idx == -1:
        return text[:120]
    start = max(0, idx - radius)
    end = min(len(text), idx + radius)
    return text[start:end].strip()


def lookup_fwa_status(raw_tag: str) -> FwaLookupResult:
    """High level entry point: normalize tag, fetch page, parse result."""
    tag = normalize_tag(raw_tag)
    source_url = f"{BASE_URL}?tag={tag}"
    html = fetch_member_page(tag)
    return parse_member_page(html, tag, source_url)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fwa_lookup.py <playertag>")
        sys.exit(1)

    try:
        result = lookup_fwa_status(sys.argv[1])
    except (ValueError, FwaLookupError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print(f"Tag: {result.tag}")
    print(f"Source: {result.source_url}")
    print(f"Found: {result.found}")
    if result.found:
        print(f"Name: {result.player_name}")
        print(f"Banned: {result.banned}")
        print(f"Reason: {result.reason}")
