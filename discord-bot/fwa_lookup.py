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
import threading
import time
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

SCRAPINGANT_URL = "https://api.scrapingant.com/v2/general"
SCRAPINGANT_TIMEOUT = 70

TAG_RE = re.compile(r"^[0289PYLQGRJCUV]{3,12}$")
TAG_ALLOWED_CHARS = "0289PYLQGRJCUV"

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
        raise ValueError(
            f"'{raw_tag}' doesn't look like a valid Clash of Clans player tag "
            f"(only these characters are allowed: {TAG_ALLOWED_CHARS})"
        )
    return tag


def _looks_like_cloudflare_challenge(html: str, status_code: int) -> bool:
    """
    A 403/503 alone doesn't necessarily mean Cloudflare blocked us — only
    treat it as a Cloudflare challenge if the body also contains one of the
    known challenge markers. Otherwise it's a genuine site error, and
    escalating through cloudscraper/ScraperAPI/ScrapingAnt won't fix it
    (it just burns paid quota for no benefit).
    """
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


def _fetch_with_scrapingant(url: str) -> tuple[int, str]:
    api_key = os.environ.get("SCRAPINGANT_API_KEY")
    if not api_key:
        raise FwaLookupError("SCRAPINGANT_API_KEY is not configured")

    params = {
        "url": url,
        "x-api-key": api_key,
        "browser": "true",
    }
    request_url = f"{SCRAPINGANT_URL}?{urllib.parse.urlencode(params)}"
    resp = requests.get(request_url, timeout=SCRAPINGANT_TIMEOUT)
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
      4. ScrapingAnt (with browser=true), used as a backup if ScraperAPI
         fails or its credits/quota are exhausted. Requires
         SCRAPINGANT_API_KEY to be set; skipped (with a warning) if it isn't.

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
        if status_code in (403, 503):
            raise FwaLookupError(f"Site returned an unexpected error ({status_code})")
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
        if status_code in (403, 503):
            raise FwaLookupError(f"Site returned an unexpected error ({status_code})")
        if status_code >= 400:
            raise FwaLookupError(f"Site returned error {status_code}")
        return html

    # Fall back to ScraperAPI
    scraperapi_ok = False
    if not os.environ.get("SCRAPERAPI_KEY"):
        logger.warning(
            "SCRAPERAPI_KEY is not set; skipping ScraperAPI fallback for tag %s", tag
        )
    else:
        try:
            status_code, html = _fetch_with_scraperapi(url)
            scraperapi_ok = True
        except requests.RequestException:
            logger.warning("ScraperAPI request failed for tag %s", tag, exc_info=True)
            status_code, html = 0, ""

        if scraperapi_ok and status_code >= 400:
            # A 4xx from ScraperAPI often means the account is out of
            # credits/quota (e.g. 403/429), not that the site itself is
            # unreachable, so this is exactly when we want to try the
            # ScrapingAnt backup below instead of giving up.
            logger.warning(
                "ScraperAPI returned status %s for tag %s: %s", status_code, tag, html[:300]
            )
            scraperapi_ok = False

        if scraperapi_ok and not _looks_like_cloudflare_challenge(html, status_code):
            return html

    # Fall back to ScrapingAnt (used when ScraperAPI is unset, erroring, or
    # its credits/quota have run out).
    if not os.environ.get("SCRAPINGANT_API_KEY"):
        logger.warning(
            "SCRAPINGANT_API_KEY is not set; skipping ScrapingAnt fallback for tag %s", tag
        )
        raise FwaLookupError(
            "The FWA lookup site is behind a Cloudflare check that couldn't be bypassed."
        )

    try:
        status_code, html = _fetch_with_scrapingant(url)
    except requests.RequestException:
        logger.warning("ScrapingAnt request failed for tag %s", tag, exc_info=True)
        raise FwaLookupError(
            "The FWA lookup site is behind a Cloudflare check that couldn't be bypassed."
        )

    if status_code in (403, 503) and not _looks_like_cloudflare_challenge(html, status_code):
        raise FwaLookupError(f"Site returned an unexpected error ({status_code})")

    if status_code >= 400:
        logger.warning(
            "ScrapingAnt returned status %s for tag %s: %s", status_code, tag, html[:300]
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


def _get_main_content_text(soup: BeautifulSoup) -> tuple[str, bool]:
    """
    Return (text, used_fallback) for the "main content" region of the page.

    Nav bars, footers, and help text can contain words like "banned" or
    "not found" that have nothing to do with the player being looked up, so
    keyword matching should prefer the largest table/div on the page (which
    is where cc.fwafarm.com renders the actual member details) over the
    whole flattened page text. If no clear candidate region is found, fall
    back to the whole page text and tell the caller so it can log it.
    """
    best_text = ""
    for el in soup.find_all(["table", "div"]):
        text = el.get_text(" ", strip=True)
        if len(text) > len(best_text):
            best_text = text

    if len(best_text) >= 50:
        return best_text, False

    return soup.get_text(" ", strip=True), True


def parse_member_page(html: str, tag: str, source_url: str) -> FwaLookupResult:
    """
    Parse the member.php HTML for player name + ban status.

    The exact markup of cc.fwafarm.com can change, so this parser is
    deliberately layered:
      1. Look for common structured elements (tables, definition lists,
         elements with class/id hints like 'name', 'status', 'ban').
      2. Fall back to scanning the visible text of the main content region
         for ban/not-found keywords (falling back further to the whole
         page's text only if no main content region can be identified).

    Raises FwaLookupError instead of silently reporting "not banned" if the
    page can't be confidently classified either way — reporting a clean
    result on a page we don't understand is the worst failure mode for a
    ban-checking tool.
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(separator=" ", strip=True)
    lowered_text = page_text.lower()

    if not page_text or len(page_text) < 20:
        raise FwaLookupError("Received an empty page from the FWA lookup site.")

    main_text, used_fallback = _get_main_content_text(soup)
    if used_fallback:
        logger.warning(
            "No clear main-content region found for tag %s; falling back to "
            "whole-page keyword matching",
            tag,
        )
    lowered_main_text = main_text.lower()

    if any(keyword in lowered_main_text for keyword in _NOT_FOUND_KEYWORDS):
        return FwaLookupResult(tag=tag, source_url=source_url, found=False)

    player_name = _extract_player_name(soup, page_text)

    banned: Optional[bool] = None
    reason = None
    confidently_not_banned = False

    ban_el = soup.find(
        lambda el: el.name in ("td", "span", "div", "li", "p", "b", "strong")
        and el.get("class")
        and any("ban" in c.lower() or "status" in c.lower() for c in el.get("class"))
    )
    if ban_el is not None:
        ban_text = ban_el.get_text(" ", strip=True)
        lowered_ban_text = ban_text.lower()
        if "not banned" in lowered_ban_text:
            banned = False
            confidently_not_banned = True
        elif "banned" in lowered_ban_text:
            banned = True
            reason = ban_text
    else:
        table_row_text = _find_labelled_row_text(soup, ("status", "ban", "banned"))
        if table_row_text is not None:
            lowered_row_text = table_row_text.lower()
            if "not banned" in lowered_row_text:
                banned = False
                confidently_not_banned = True
            elif "banned" in lowered_row_text:
                banned = True
                reason = table_row_text

    if banned is None:
        if "not banned" in lowered_main_text or "no ban" in lowered_main_text:
            banned = False
            confidently_not_banned = True
        elif any(keyword in lowered_main_text for keyword in _BAN_KEYWORDS):
            banned = True
        elif player_name is not None:
            # cc.fwafarm.com doesn't put an explicit "not banned" marker on
            # clean players' pages — it simply omits any ban text. If we
            # successfully parsed real member details (a name) and found no
            # ban keywords anywhere in the main content, that's a confident
            # "not banned", not an ambiguous parse.
            banned = False
            confidently_not_banned = True

    if banned is None:
        raise FwaLookupError(
            "Could not confidently determine ban status for this player — "
            "please check manually on ChocolateClash."
        )

    if banned:
        # Prefer the real ban explanation from the site's "Member Notes"
        # table over a raw text snippet, which tends to include unrelated
        # page boilerplate. If no structured note is found, it's better to
        # show no reason at all than a garbled snippet.
        note_reason = _extract_ban_reason(soup)
        if note_reason:
            reason = note_reason
        elif reason is None or reason.lower() == "banned":
            reason = None

    if player_name is None and confidently_not_banned and not any(
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


_NAME_LABEL_RE = re.compile(r"^\s*names?\s*:?\s*$", re.IGNORECASE)
_NAME_TEXT_RE = re.compile(
    r"\bnames?\s*:\s*(.{1,40}?)(?=\s*(?:this player has changed|current clan|synchronized|donates|town hall|rank|$))",
    re.IGNORECASE,
)


def _extract_name_after_label(soup: BeautifulSoup) -> Optional[str]:
    """
    cc.fwafarm.com renders the player name as plain text right after a
    `<b>Name: </b>` (or `<b>Names: </b>` for players who have changed their
    in-game name) label, not inside its own element. Walk the siblings
    after that label up to the next tag/line break to reconstruct the full
    name, including names containing spaces.
    """
    label_el = soup.find("b", string=_NAME_LABEL_RE)
    if label_el is None:
        return None

    parts: list[str] = []
    for sibling in label_el.next_siblings:
        if getattr(sibling, "name", None) == "br":
            break
        if getattr(sibling, "name", None) is not None:
            # Hit another element (e.g. a highlighted "name changed" notice)
            # before a line break — stop, since that's not part of the name.
            break
        parts.append(str(sibling))

    name = "".join(parts).strip()
    return name or None


_SITE_BRAND_WORDS = ("fwa", "chocolateclash", "farm")


def _extract_player_name(soup: BeautifulSoup, page_text: str) -> Optional[str]:
    for tag_name in ("h1", "h2", "h3"):
        el = soup.find(tag_name)
        if el:
            text = el.get_text(" ", strip=True)
            lowered = text.lower()
            if (
                text
                and len(text) < 60
                and not any(word in lowered for word in _SITE_BRAND_WORDS)
            ):
                return text

    label_name = _extract_name_after_label(soup)
    if label_name:
        return label_name

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

    # Fall back to scanning the rendered page text for a "Name: X" / "Names: X"
    # pattern, since this site often renders member details as plain text
    # rather than structured table rows/spans.
    match = _NAME_TEXT_RE.search(page_text)
    if match:
        candidate = match.group(1).strip()
        if candidate:
            return candidate

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


_MEMBER_NOTES_LABEL_RE = re.compile(r"member\s*notes", re.IGNORECASE)
_MAX_REASON_LENGTH = 300


def _extract_ban_reason(soup: BeautifulSoup) -> Optional[str]:
    """
    cc.fwafarm.com stores the actual ban explanation in a "Member Notes"
    table (columns: Metadata / Note / Author) rather than anywhere near the
    "BANNED!" marker itself. Pull the note text from the first data row's
    highlighted "Note" cell (class "bigted"), skipping the header row.
    """
    label = soup.find(string=_MEMBER_NOTES_LABEL_RE)
    if label is None:
        return None

    table = label.find_next("table")
    if table is None:
        return None

    for row in table.find_all("tr"):
        note_cell = row.find("td", class_="bigted")
        if note_cell is None:
            continue
        text = note_cell.get_text(" ", strip=True)
        if not text or text.lower() == "note":
            continue
        if len(text) > _MAX_REASON_LENGTH:
            text = text[:_MAX_REASON_LENGTH].rstrip() + "…"
        return text

    return None


_CACHE_TTL_SECONDS = 300
_lookup_cache: dict[str, tuple[FwaLookupResult, float]] = {}
_cache_lock = threading.Lock()


def _get_cached_result(tag: str) -> Optional[FwaLookupResult]:
    with _cache_lock:
        entry = _lookup_cache.get(tag)
        if entry is None:
            return None
        result, cached_at = entry
        if time.monotonic() - cached_at > _CACHE_TTL_SECONDS:
            del _lookup_cache[tag]
            return None
        return result


def _set_cached_result(tag: str, result: FwaLookupResult) -> None:
    with _cache_lock:
        _lookup_cache[tag] = (result, time.monotonic())


def lookup_fwa_status(raw_tag: str) -> FwaLookupResult:
    """
    High level entry point: normalize tag, fetch page, parse result.

    Results are cached in-process per normalized tag for _CACHE_TTL_SECONDS
    to avoid re-fetching (and re-burning paid ScraperAPI/ScrapingAnt quota)
    on repeated lookups for the same player in a short window. The cache is
    thread-safe since lookups run inside a thread pool executor.
    """
    tag = normalize_tag(raw_tag)

    cached_result = _get_cached_result(tag)
    if cached_result is not None:
        return cached_result

    source_url = f"{BASE_URL}?tag={tag}"
    html = fetch_member_page(tag)
    result = parse_member_page(html, tag, source_url)
    _set_cached_result(tag, result)
    return result


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
