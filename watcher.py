#!/usr/bin/env python3
"""Daily watcher for a second-hand Trek Domane AL 3 (disc, 58 cm) near Richmond VIC.

Checks Gumtree AU, bikesales.com.au and eBay AU, and pushes new matches to
ntfy.sh (email fallback). Facebook Marketplace is deliberately NOT scraped.

    python watcher.py --dry-run            # test: print everything, send nothing, remember nothing
    python watcher.py                      # real run
    python watcher.py --test-notify        # send a test push
    python watcher.py --install-schedule   # set up the daily 7am run (launchd / Task Scheduler / cron)
    python watcher.py --uninstall-schedule # turn it off
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import logging.handlers
import math
import os
import platform
import random
import re
import shutil
import smtplib
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
import yaml

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.yaml"
SEEN_PATH = HERE / "seen.json"
LOG_PATH = HERE / "watcher.log"
TASK_NAME = "TrekDomaneWatcher"
LAUNCHD_LABEL = "com.user.trek-domane-watcher"
CRON_MARKER = "# trek-domane-watcher"

log = logging.getLogger("watcher")


# --------------------------------------------------------------------------
# Suburbs near Richmond VIC: name -> (lat, lon, postcode). Approximate centroids
# (within ~1 km), covering everything within ~12 km so a 10 km radius works.
# A VIC suburb that is not in this table is treated as further away.
# --------------------------------------------------------------------------
SUBURBS = {
    "richmond": (-37.8183, 145.0018, "3121"), "burnley": (-37.8270, 145.0080, "3121"),
    "cremorne": (-37.8300, 144.9930, "3121"), "melbourne": (-37.8136, 144.9631, "3000"),
    "melbourne cbd": (-37.8136, 144.9631, "3000"), "east melbourne": (-37.8130, 144.9850, "3002"),
    "west melbourne": (-37.8070, 144.9420, "3003"), "north melbourne": (-37.7990, 144.9460, "3051"),
    "southbank": (-37.8250, 144.9640, "3006"), "docklands": (-37.8170, 144.9460, "3008"),
    "south melbourne": (-37.8340, 144.9580, "3205"), "albert park": (-37.8420, 144.9550, "3206"),
    "middle park": (-37.8510, 144.9620, "3206"), "port melbourne": (-37.8390, 144.9420, "3207"),
    "st kilda": (-37.8640, 144.9810, "3182"), "st kilda west": (-37.8590, 144.9750, "3182"),
    "st kilda east": (-37.8670, 145.0000, "3183"), "balaclava": (-37.8690, 144.9940, "3183"),
    "elwood": (-37.8820, 144.9870, "3184"), "ripponlea": (-37.8770, 144.9960, "3185"),
    "elsternwick": (-37.8850, 145.0010, "3185"), "gardenvale": (-37.8970, 145.0080, "3185"),
    "brighton": (-37.9060, 144.9870, "3186"), "brighton east": (-37.9030, 145.0080, "3187"),
    "windsor": (-37.8560, 144.9920, "3181"), "prahran": (-37.8510, 144.9930, "3181"),
    "south yarra": (-37.8380, 144.9920, "3141"), "toorak": (-37.8410, 145.0170, "3142"),
    "armadale": (-37.8560, 145.0190, "3143"), "kooyong": (-37.8400, 145.0330, "3144"),
    "malvern": (-37.8620, 145.0280, "3144"), "malvern east": (-37.8740, 145.0420, "3145"),
    "glen iris": (-37.8540, 145.0590, "3146"), "ashburton": (-37.8650, 145.0820, "3147"),
    "ashwood": (-37.8660, 145.1050, "3147"), "chadstone": (-37.8850, 145.0950, "3148"),
    "caulfield north": (-37.8740, 145.0240, "3161"), "caulfield": (-37.8820, 145.0230, "3162"),
    "caulfield east": (-37.8800, 145.0440, "3145"), "caulfield south": (-37.8950, 145.0270, "3162"),
    "glen huntly": (-37.8900, 145.0420, "3163"), "carnegie": (-37.8870, 145.0570, "3163"),
    "murrumbeena": (-37.8900, 145.0700, "3163"), "hughesdale": (-37.8950, 145.0770, "3166"),
    "oakleigh": (-37.8990, 145.0880, "3166"), "ormond": (-37.9030, 145.0410, "3204"),
    "mckinnon": (-37.9100, 145.0390, "3204"), "bentleigh": (-37.9180, 145.0350, "3204"),
    "hawthorn": (-37.8220, 145.0350, "3122"), "hawthorn east": (-37.8300, 145.0450, "3123"),
    "camberwell": (-37.8380, 145.0720, "3124"), "canterbury": (-37.8240, 145.0810, "3126"),
    "surrey hills": (-37.8260, 145.1000, "3127"), "mont albert": (-37.8190, 145.1050, "3127"),
    "burwood": (-37.8490, 145.1150, "3125"), "box hill": (-37.8190, 145.1230, "3128"),
    "balwyn": (-37.8100, 145.0830, "3103"), "deepdene": (-37.8100, 145.0650, "3103"),
    "balwyn north": (-37.7930, 145.0850, "3104"), "kew": (-37.8060, 145.0300, "3101"),
    "kew east": (-37.7960, 145.0520, "3102"), "bulleen": (-37.7680, 145.0880, "3105"),
    "abbotsford": (-37.8030, 144.9990, "3067"), "collingwood": (-37.8020, 144.9880, "3066"),
    "fitzroy": (-37.7980, 144.9780, "3065"), "fitzroy north": (-37.7880, 144.9840, "3068"),
    "clifton hill": (-37.7880, 144.9950, "3068"), "carlton": (-37.8000, 144.9670, "3053"),
    "carlton north": (-37.7850, 144.9720, "3054"), "princes hill": (-37.7820, 144.9670, "3054"),
    "parkville": (-37.7870, 144.9510, "3052"), "brunswick": (-37.7670, 144.9590, "3056"),
    "brunswick east": (-37.7710, 144.9720, "3057"), "brunswick west": (-37.7640, 144.9440, "3055"),
    "northcote": (-37.7700, 145.0000, "3070"), "thornbury": (-37.7550, 145.0050, "3071"),
    "preston": (-37.7420, 145.0090, "3072"), "reservoir": (-37.7170, 145.0070, "3073"),
    "fairfield": (-37.7790, 145.0170, "3078"), "alphington": (-37.7800, 145.0300, "3078"),
    "ivanhoe": (-37.7690, 145.0450, "3079"), "ivanhoe east": (-37.7730, 145.0610, "3079"),
    "eaglemont": (-37.7630, 145.0640, "3084"), "heidelberg": (-37.7560, 145.0670, "3084"),
    "rosanna": (-37.7420, 145.0660, "3084"), "coburg": (-37.7440, 144.9660, "3058"),
    "coburg north": (-37.7290, 144.9640, "3058"), "pascoe vale south": (-37.7420, 144.9390, "3044"),
    "moonee ponds": (-37.7650, 144.9200, "3039"), "ascot vale": (-37.7790, 144.9220, "3032"),
    "travancore": (-37.7810, 144.9380, "3032"), "flemington": (-37.7880, 144.9300, "3031"),
    "kensington": (-37.7940, 144.9260, "3031"), "essendon": (-37.7520, 144.9190, "3040"),
    "footscray": (-37.8000, 144.9000, "3011"), "seddon": (-37.8070, 144.8920, "3011"),
    "yarraville": (-37.8160, 144.8890, "3013"), "west footscray": (-37.8010, 144.8800, "3012"),
    "maribyrnong": (-37.7740, 144.8890, "3032"), "spotswood": (-37.8300, 144.8850, "3015"),
    "williamstown": (-37.8600, 144.8970, "3016"), "newport": (-37.8440, 144.8830, "3015"),
}
STATES = ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT")


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
@dataclass
class Listing:
    source: str
    url: str
    title: str
    card_text: str = ""
    description: str = ""
    price: str = ""
    location: str = ""          # human-readable, e.g. "Richmond VIC"
    distance_km: float | None = None
    labels: list[str] = field(default_factory=list)
    reject_reason: str = ""
    detail_failed: bool = False


@dataclass
class SourceResult:
    name: str
    ok: bool = True
    error: str = ""
    search_url: str = ""
    found: int = 0
    new: int = 0
    checked: int = 0
    matches: list[Listing] = field(default_factory=list)
    rejected: list[Listing] = field(default_factory=list)


class SourceError(Exception):
    pass


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------
def norm(text: str) -> str:
    text = (text or "").lower().replace("‑", "-")
    text = re.sub(r"[-_/]", " ", text)
    return re.sub(r"\s+", " ", text)


def term_re(term: str) -> re.Pattern:
    t = re.escape(norm(term).strip()).replace(r"\ ", r"\s?")
    return re.compile(rf"(?<![a-z0-9]){t}(?![a-z0-9])")


def has_any(text: str, terms) -> str | None:
    for t in terms:
        if term_re(t).search(text):
            return t
    return None


OTHER_SIZE_RE = re.compile(
    r"(?<![a-z0-9])(44|47|49|50|51|52|53|54|55|56|57|60|61|62)\s?cm(?![a-z0-9])"
    r"|(?:frame\s?size|size)\s?:?\s?(44|47|49|50|52|54|56|60|61|62|xxs|xs|s|sm|small|m|md|medium|ml|l|lg|large)(?![a-z0-9])"
)
YEAR_RE = re.compile(r"(?<![0-9])(19[89][0-9]|20[0-4][0-9])(?![0-9])")
# In descriptions only trust years that clearly describe the bike (pages also show posting dates).
DESC_YEAR_RE = re.compile(
    r"(?:model|year|my|purchased|bought|built)\s?(?:year)?\s?:?\s?(?:in\s)?(20[0-4][0-9])(?![0-9])"
    r"|(?<![0-9/\-\.])(20[0-4][0-9])\s(?:trek|domane|model)"
)


def bike_years(title: str, body: str) -> list[int]:
    this_year = dt.date.today().year
    ys = [int(y) for y in YEAR_RE.findall(title)]
    ys += [int(a or b) for a, b in DESC_YEAR_RE.findall(body)]
    return [y for y in ys if y <= this_year + 1]


def evaluate(lst: Listing, mcfg: dict) -> bool:
    """Apply the matching rules. Sets labels / reject_reason. Returns True if it's a match."""
    title = norm(lst.title)
    body = norm(lst.description or lst.card_text)
    text = f"{title} {body}"

    for t in mcfg["must_contain_all"]:
        if not term_re(t).search(text):
            lst.reject_reason = f"no '{t}'"
            return False
    if not has_any(text, mcfg["must_contain_any"]):
        lst.reject_reason = "not an AL 3"
        return False
    bad = has_any(title, mcfg["exclude_title_terms"])
    if bad:
        lst.reject_reason = f"excluded ('{bad}' in title)"
        return False
    bad = has_any(body, mcfg.get("exclude_description_terms", []))
    if bad:
        lst.reject_reason = f"excluded ('{bad}' in description)"
        return False

    # Size
    if has_any(text, mcfg["size_terms"]):
        lst.labels.append("58 CM")
    elif OTHER_SIZE_RE.search(text):
        m = OTHER_SIZE_RE.search(text)
        if mcfg.get("drop_other_sizes", True):
            lst.reject_reason = f"other size ('{m.group(0).strip()}')"
            return False
        lst.labels.append(f"SIZE? ({m.group(0).strip()})")
    else:
        lst.labels.append("SIZE UNKNOWN")

    # Brakes
    years = bike_years(title, body)
    disc_hit = has_any(text, mcfg["disc_terms"]) or any(y >= mcfg["disc_min_year"] for y in years)
    rim_hit = has_any(text, mcfg["rim_brake_terms"])
    if rim_hit and not disc_hit:
        lst.reject_reason = f"rim brake ('{rim_hit}')"
        return False
    lst.labels.append("CHECK BRAKES" if (rim_hit or not disc_hit) else "DISC")
    if has_any(text, ["gen 3", "gen3", "gen 4", "gen4"]) or any(y >= 2022 for y in years):
        lst.labels.append("GEN 3+")
    return True


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------
LOC_RE = re.compile(r"([A-Z][A-Za-z'\.]+(?:[ \-][A-Z][A-Za-z'\.]+){0,3}),?\s+(" + "|".join(STATES) + r")\b(?:\s+(\d{4}))?")
POSTCODE_RE = re.compile(r"(?<!\d)(3\d{3})(?!\d)")
KM_AWAY_RE = re.compile(r"(\d+(?:\.\d+)?)\s?km(?:\s+away)?", re.I)


def locate(lst: Listing, cfg: dict, server_side_radius: bool, extra_hint: str = "") -> bool:
    """Fill in location/distance. Returns False if clearly outside the radius."""
    suburbs = {**SUBURBS, **{k.lower(): tuple(v) for k, v in (cfg.get("extra_suburbs") or {}).items()}}
    home = suburbs.get(cfg["search"]["suburb"].lower(), SUBURBS["richmond"])
    radius = float(cfg["search"]["radius_km"])
    by_postcode = {}
    for name, v in suburbs.items():
        by_postcode.setdefault(v[2], (name, v))

    hay = f"{extra_hint}\n{lst.card_text}"
    state = None
    for m in LOC_RE.finditer(hay):
        name, st, pc = m.group(1).strip(), m.group(2), m.group(3)
        # Strip leading junk words like "Located in Richmond"
        words = name.split()
        for i in range(len(words)):
            cand = " ".join(words[i:]).lower()
            if cand in suburbs:
                lst.location = f"{' '.join(words[i:])} {st}"
                lst.distance_km = haversine_km(home, suburbs[cand])
                return lst.distance_km <= radius
        state = state or st
        if pc and pc in by_postcode:
            n, v = by_postcode[pc]
            lst.location = f"{name} {st} {pc}"
            lst.distance_km = haversine_km(home, v)
            return lst.distance_km <= radius
        if not lst.location:
            lst.location = f"{name} {st}"
    # Gumtree puts the suburb in the URL: /s-ad/<suburb>/<category>/...
    m = re.search(r"/s-ad/([a-z0-9\-]+)/", lst.url)
    if m:
        cand = m.group(1).replace("-", " ")
        if cand in suburbs:
            lst.location = lst.location or f"{cand.title()} VIC"
            lst.distance_km = haversine_km(home, suburbs[cand])
            return lst.distance_km <= radius
        lst.location = lst.location or cand.title()
    m = KM_AWAY_RE.search(hay)
    if m and "away" in m.group(0).lower():
        lst.distance_km = float(m.group(1))
        return lst.distance_km <= radius

    if state and state != "VIC":
        return False
    if server_side_radius:
        return True                       # the site already applied the radius
    if state == "VIC" and lst.location:
        return False                      # named VIC suburb not in our near-Richmond table
    lst.labels.append("CHECK LOCATION")
    return True


def find_price(text: str) -> str:
    m = re.search(r"(?:AU\s?)?\$\s?\d[\d,]*(?:\.\d{2})?", text or "")
    if m:
        return m.group(0).replace(" ", "")
    for word in ("Free", "Negotiable", "Swap/Trade"):
        if word.lower() in (text or "").lower():
            return word
    return "price n/a"


# --------------------------------------------------------------------------
# Browser helpers
# --------------------------------------------------------------------------
BLOCK_MARKERS = [
    "pardon our interruption", "access denied", "verify you are a human", "verify you are human",
    "are you a robot", "captcha", "request unsuccessful", "incapsula", "checking your browser",
    "unusual traffic", "please enable cookies", "you have been blocked", "bot protection",
    "press & hold", "security check to access",
]
NO_RESULT_RE = re.compile(
    r"no results|(?<![0-9,])0 (?:results|ads|listings|items)|no matching|didn't find|did not find|"
    r"couldn't find|could not find|no ads found|no listings|no exact matches|try a different search|"
    r"we found 0"
)

COLLECT_JS = r"""
(pattern) => {
  const re = new RegExp(pattern);
  const clean = h => h.split('#')[0].split('?')[0];
  const out = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = clean(a.href);
    if (!re.test(href)) continue;
    let card = a;
    for (let i = 0; i < 8; i++) {
      const p = card.parentElement;
      if (!p || p === document.body) break;
      const ids = new Set([...p.querySelectorAll('a[href]')].map(x => clean(x.href)).filter(h => re.test(h)));
      if (ids.size > 1) break;
      card = p;
    }
    const title = (a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || '').trim();
    const text = (card.innerText || '').trim().slice(0, 2500);
    const prev = out.get(href);
    if (!prev) out.set(href, {url: href, title, text});
    else {
      if (title.length > prev.title.length && title.length < 200) prev.title = title;
      if (text.length > prev.text.length) prev.text = text;
    }
  }
  return [...out.values()];
}
"""

CUT_MARKERS = [
    "similar ads", "similar items", "related items", "you may also like", "sponsored items",
    "people who viewed this", "explore related", "more from this seller", "recommended for you",
    "other ads from", "similar listings", "you might also like", "related searches",
]


class Browser:
    def __init__(self, cfg: dict):
        from playwright.sync_api import sync_playwright
        self.cfg = cfg
        self._pw = sync_playwright().start()
        bcfg = cfg.get("browser") or {}
        kw = dict(headless=bcfg.get("headless", True), args=["--disable-blink-features=AutomationControlled"])
        if bcfg.get("executable_path"):
            kw["executable_path"] = bcfg["executable_path"]
        try:
            self._browser = self._pw.chromium.launch(**kw)
        except Exception as e:
            self._pw.stop()
            if "Executable doesn't exist" in str(e):
                raise SystemExit("Playwright's Chromium is not installed. Run:  python -m playwright install chromium")
            raise
        pol = cfg["politeness"]
        self.ctx = self._browser.new_context(
            user_agent=pol["user_agent"], locale="en-AU", timezone_id="Australia/Melbourne",
            viewport={"width": 1366, "height": 900},
        )
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(45000)
        self._first = True

    def pause(self):
        pol = self.cfg["politeness"]
        if not self._first:
            time.sleep(random.uniform(pol["delay_seconds_min"], pol["delay_seconds_max"]))
        self._first = False

    def goto(self, url: str):
        self.pause()
        resp = self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        self.dismiss_popups()
        return resp

    def dismiss_popups(self):
        for label in ("Accept all", "Accept All", "Accept", "I agree", "Got it", "OK"):
            try:
                btn = self.page.get_by_role("button", name=label, exact=True)
                if btn.count() and btn.first.is_visible():
                    btn.first.click(timeout=2000)
                    self.page.wait_for_timeout(500)
                    return
            except Exception:
                pass

    def scroll(self):
        for _ in range(4):
            self.page.mouse.wheel(0, 2500)
            self.page.wait_for_timeout(700)

    def body_text(self) -> str:
        try:
            return self.page.inner_text("body", timeout=10000)
        except Exception:
            return ""

    def collect(self, pattern: str) -> list[dict]:
        return self.page.evaluate(COLLECT_JS, pattern)

    def detail_text(self, url: str) -> str:
        self.goto(url)
        text = ""
        for sel in ("main", "[role=main]", "body"):
            try:
                if self.page.locator(sel).count():
                    text = self.page.locator(sel).first.inner_text(timeout=10000)
                    if len(text) > 200:
                        break
            except Exception:
                continue
        # eBay keeps the seller's description in an iframe
        for fr in self.page.frames:
            if "ebaydesc" in (fr.url or ""):
                try:
                    text += "\n" + fr.inner_text("body", timeout=10000)
                except Exception:
                    pass
        low = text.lower()
        cut = min([i for i in (low.find(m, 300) for m in CUT_MARKERS) if i > 0], default=len(text))
        return text[:cut][:15000]

    def close(self):
        try:
            self._browser.close()
        finally:
            self._pw.stop()


def check_page(br: Browser, resp, items: list, source: str):
    """Raise SourceError if the page looks blocked or broken."""
    text = br.body_text().lower()
    status = resp.status if resp else None
    if items:
        return
    if any(m in text for m in BLOCK_MARKERS) or (status and status in (401, 403, 429)):
        raise SourceError(f"blocked by the site's bot protection (HTTP {status})")
    if status and status >= 400:
        raise SourceError(f"HTTP {status} from search page")
    if NO_RESULT_RE.search(text):
        return
    raise SourceError("no listings found and no 'no results' message - page layout may have changed")


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
def scrape_with_browser(br, name, search_url, pattern, cfg, seen, res: SourceResult, server_side_radius,
                        skip_title=None):
    resp = br.goto(search_url)
    res.search_url = br.page.url
    br.scroll()
    items = [i for i in br.collect(pattern) if not (skip_title and skip_title(i))]
    check_page(br, resp, items, name)
    res.found = len(items)
    process_items(br, name, items, cfg, seen, res, server_side_radius)


def process_items(br, name, items, cfg, seen, res: SourceResult, server_side_radius, detail_fn=None):
    limit = cfg["politeness"]["max_detail_pages_per_source"]
    for it in items:
        url = canonical(it["url"])
        if url in seen["listings"]:
            continue
        res.new += 1
        if res.checked >= limit:
            log.info("  [%s] detail limit reached; %s left for next run", name, url)
            continue
        title = (it.get("title") or "").strip() or (it.get("text") or "").split("\n")[0]
        lst = Listing(source=name, url=url, title=title[:200], card_text=it.get("text", ""))
        lst.price = it.get("price") or find_price(lst.card_text)
        # Cheap pre-check on the card so we don't open obviously irrelevant ads.
        if not locate(lst, cfg, server_side_radius, it.get("location_hint", "")):
            lst.reject_reason = f"outside {cfg['search']['radius_km']} km ({lst.location or 'unknown'})"
        else:
            try:
                lst.description = detail_fn(it) if detail_fn else br.detail_text(url)
                res.checked += 1
            except Exception as e:
                log.warning("  [%s] could not open %s: %s", name, url, e)
                lst.description, lst.detail_failed = "", True
                res.checked += 1
            if lst.price == "price n/a" and lst.description:
                lst.price = find_price(lst.description)
            if not lst.location and lst.description:
                if not locate(lst, cfg, server_side_radius, lst.description[:3000]):
                    lst.reject_reason = f"outside {cfg['search']['radius_km']} km ({lst.location})"
                if lst.location and "CHECK LOCATION" in lst.labels:
                    lst.labels.remove("CHECK LOCATION")
                lst.labels = list(dict.fromkeys(lst.labels))
            if not lst.reject_reason:
                evaluate(lst, cfg["match"])
        (res.rejected if lst.reject_reason else res.matches).append(lst)


def canonical(url: str) -> str:
    p = urlsplit(url)
    path = p.path
    m = re.search(r"/itm/(?:[^/]+/)?(\d+)", path)
    if m:
        path = f"/itm/{m.group(1)}"
    return urlunsplit((p.scheme, p.netloc.lower(), path.rstrip("/"), "", ""))


def source_gumtree(br, cfg, seen, res):
    url = cfg["sources"]["gumtree"]["search_url"]
    scrape_with_browser(br, "Gumtree", url, r"gumtree\.com\.au/s-ad/", cfg, seen, res, server_side_radius=True)


def source_bikesales(br, cfg, seen, res):
    url = cfg["sources"]["bikesales"].get("search_url")
    pattern = r"bikesales\.com\.au/.*details/"
    if url:
        scrape_with_browser(br, "bikesales", url, pattern, cfg, seen, res, server_side_radius=False)
        return
    # Use the site's own search box.
    resp = br.goto("https://www.bikesales.com.au/")
    text = br.body_text().lower()
    if any(m in text for m in BLOCK_MARKERS) or (resp and resp.status in (401, 403, 429)):
        raise SourceError(f"blocked by the site's bot protection (HTTP {resp.status if resp else '?'})")
    box = None
    for sel in ('input[type="search"]', 'input[placeholder*="earch" i]', 'input[name*="keyword" i]',
                'input[name="q"]', 'input[aria-label*="earch" i]'):
        loc = br.page.locator(sel)
        for i in range(loc.count()):
            if loc.nth(i).is_visible():
                box = loc.nth(i)
                break
        if box:
            break
    if box is None:
        raise SourceError("couldn't find the search box on the home page - layout may have changed "
                          "(paste a search URL into config.yaml > sources.bikesales.search_url)")
    box.click()
    box.fill(cfg["search"]["keywords"])
    br.pause()
    box.press("Enter")
    try:
        br.page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    res.search_url = br.page.url
    log.info("  [bikesales] search box led to %s", br.page.url)
    br.scroll()
    items = br.collect(pattern)
    check_page(br, None, items, "bikesales")
    res.found = len(items)
    process_items(br, "bikesales", items, cfg, seen, res, server_side_radius=False)


def source_ebay(br, cfg, seen, res):
    ecfg = cfg["sources"]["ebay"]
    cid = ecfg.get("api_client_id") or os.environ.get("EBAY_CLIENT_ID")
    secret = ecfg.get("api_client_secret") or os.environ.get("EBAY_CLIENT_SECRET")
    if cid and secret:
        return ebay_api(cfg, seen, res, cid, secret)
    scrape_with_browser(br, "eBay", ecfg["search_url"], r"ebay\.com\.au/itm/\d", cfg, seen, res,
                        server_side_radius=True,
                        skip_title=lambda i: "shop on ebay" in (i.get("title") or i.get("text") or "").lower())


def ebay_api(cfg, seen, res, cid, secret):
    s = cfg["search"]
    tok = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token", auth=(cid, secret), timeout=30,
        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
    )
    if tok.status_code != 200:
        raise SourceError(f"eBay API login failed (HTTP {tok.status_code})")
    hdr = {"Authorization": f"Bearer {tok.json()['access_token']}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_AU",
           "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country=AU,zip={s['postcode']}"}
    base = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    queries = [  # pickup near the postcode, and anything located in Australia (filtered by suburb below)
        f"itemLocationCountry:AU,deliveryOptions:{{SELLER_ARRANGED_LOCAL_PICKUP}},pickupCountry:AU,"
        f"pickupPostalCode:{s['postcode']},pickupRadius:{int(s['radius_km'])},pickupRadiusUnit:km",
        "itemLocationCountry:AU",
    ]
    items, ids = [], set()
    for f in queries:
        r = requests.get(base, headers=hdr, timeout=30,
                         params={"q": s["keywords"], "filter": f, "sort": "newlyListed", "limit": 100})
        if r.status_code != 200:
            raise SourceError(f"eBay API search failed (HTTP {r.status_code}): {r.text[:150]}")
        for it in r.json().get("itemSummaries", []):
            if it["itemId"] in ids:
                continue
            ids.add(it["itemId"])
            loc = it.get("itemLocation", {})
            hint = f"{loc.get('city', '')} {loc.get('stateOrProvince', '')} {loc.get('postalCode', '')}".strip()
            pc = (loc.get("postalCode") or "")[:4]
            hint_line = ""
            for name, v in SUBURBS.items():
                if v[2] == pc:
                    hint_line = f"{name.title()} VIC {v[2]}"
                    break
            if not hint_line:
                if "melbourne" not in hint.lower():
                    continue        # not near the postcode and not in Melbourne
                hint_line = "Melbourne VIC"
            items.append({
                "url": it["itemWebUrl"], "title": it.get("title", ""), "id": it["itemId"],
                "text": f"{it.get('title', '')}\n{hint}", "location_hint": hint_line,
                "price": f"${it['price']['value']}" if it.get("price") else "",
            })
        time.sleep(1)
    res.search_url = base
    res.found = len(items)

    def detail(it):
        time.sleep(random.uniform(1, 2))
        r = requests.get(f"https://api.ebay.com/buy/browse/v1/item/{it['id']}", headers=hdr, timeout=30)
        if r.status_code != 200:
            return ""
        d = r.json()
        aspects = "\n".join(f"{a['name']}: {a['value']}" for a in d.get("localizedAspects", []))
        desc = re.sub(r"<[^>]+>", " ", d.get("description", "") or d.get("shortDescription", ""))
        return f"{aspects}\n{desc}"

    process_items(None, "eBay", items, cfg, seen, res, server_side_radius=False, detail_fn=detail)


SOURCES = [("gumtree", "Gumtree", source_gumtree), ("bikesales", "bikesales", source_bikesales),
           ("ebay", "eBay", source_ebay)]


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
def notify(cfg, title: str, message: str, click: str = "", tags: str = "bike", priority: int | None = None) -> bool:
    ncfg = cfg["notify"]
    ok = False
    nt = ncfg.get("ntfy", {})
    if nt.get("enabled"):
        topic = nt.get("topic", "")
        if not topic or topic == "CHANGE-ME":
            log.error("ntfy topic not set in config.yaml (notify.ntfy.topic)")
        else:
            payload = {"topic": topic, "title": title, "message": message, "tags": tags.split(","),
                       "priority": priority or nt.get("priority", 3)}
            if click:
                payload["click"] = click
            try:
                r = requests.post(nt.get("server", "https://ntfy.sh").rstrip("/"), json=payload, timeout=20)
                ok = r.status_code == 200
                if not ok:
                    log.error("ntfy returned HTTP %s: %s", r.status_code, r.text[:200])
            except Exception as e:
                log.error("ntfy failed: %s", e)
    em = ncfg.get("email", {})
    if em.get("enabled") and (em.get("mode") == "always" or not ok):
        ok = send_email(em, title, message + (f"\n\n{click}" if click else "")) or ok
    return ok


def send_email(em, subject, body) -> bool:
    pw = em.get("password") or os.environ.get("WATCHER_SMTP_PASSWORD", "")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, em.get("from_addr") or em["username"], em["to_addr"]
    msg.set_content(body)
    try:
        port = int(em.get("smtp_port", 587))
        if port == 465:
            srv = smtplib.SMTP_SSL(em["smtp_host"], port, timeout=30)
        else:
            srv = smtplib.SMTP(em["smtp_host"], port, timeout=30)
            srv.starttls()
        with srv:
            if em.get("username"):
                srv.login(em["username"], pw)
            srv.send_message(msg)
        return True
    except Exception as e:
        log.error("email failed: %s", e)
        return False


def format_alert(lst: Listing) -> tuple[str, str]:
    where = lst.location or "location n/a"
    if lst.distance_km is not None:
        where += f" (~{lst.distance_km:.0f} km)"
    title = f"🚲 {lst.title[:80]} - {lst.price}"
    body = f"{lst.price} · {where}\n[{'] ['.join(lst.labels)}]\nvia {lst.source}\n{lst.url}"
    return title, body


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
def load_seen() -> dict:
    if SEEN_PATH.exists():
        try:
            data = json.loads(SEEN_PATH.read_text())
            data.setdefault("listings", {})
            return data
        except Exception:
            log.warning("seen.json is unreadable; starting fresh (old file kept as seen.json.bak)")
            shutil.copy(SEEN_PATH, SEEN_PATH.with_suffix(".json.bak"))
    return {"listings": {}, "last_run_date": None}


def save_seen(seen: dict):
    tmp = SEEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, indent=1, sort_keys=True))
    tmp.replace(SEEN_PATH)


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
def run(cfg, dry_run=False, only=None) -> int:
    seen = load_seen()
    results: list[SourceResult] = []
    enabled = [(k, n, f) for k, n, f in SOURCES if cfg["sources"].get(k, {}).get("enabled") and (not only or k in only)]
    needs_browser = any(not (k == "ebay" and (cfg["sources"]["ebay"].get("api_client_id")
                                              or os.environ.get("EBAY_CLIENT_ID"))) for k, _, _ in enabled)
    br = Browser(cfg) if needs_browser else None
    try:
        for key, name, fn in enabled:
            res = SourceResult(name)
            log.info("== %s ==", name)
            try:
                fn(br, cfg, seen, res)
            except SourceError as e:
                res.ok, res.error = False, str(e)
            except Exception as e:
                first = str(e).splitlines()[0] if str(e) else type(e).__name__
                net = re.search(r"net::ERR_[A-Z_]+", first)
                res.ok = False
                res.error = (f"couldn't load the site ({net.group(0)}) - offline or blocked?" if net
                             else f"{type(e).__name__}: {first[:200]}")
                log.debug(traceback.format_exc())
            results.append(res)
            report_source(res)
    finally:
        if br:
            br.close()

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    matches = [m for r in results for m in r.matches]
    failures = [r for r in results if not r.ok]
    delivered_all = True

    if dry_run:
        log.info("DRY RUN: nothing sent, seen.json not changed.")
        for m in matches:
            t, b = format_alert(m)
            log.info("WOULD SEND:\n  %s\n  %s", t, b.replace("\n", "\n  "))
        for r in failures:
            log.info("WOULD SEND: ⚠️ Bike watcher: %s failed - %s", r.name, r.error)
        return 0 if not failures else 2

    for m in matches:
        t, b = format_alert(m)
        if notify(cfg, t, b, click=m.url):
            seen["listings"][m.url] = {"first_seen": now, "title": m.title, "source": m.source, "status": "alerted"}
        else:
            delivered_all = False   # not marked seen, so it's retried next run
    for r in results:
        for rej in r.rejected:
            if rej.detail_failed:
                continue            # couldn't read the ad; look again next run
            seen["listings"][rej.url] = {"first_seen": now, "title": rej.title, "source": rej.source,
                                         "status": f"rejected: {rej.reject_reason}"}
    if failures and cfg["notify"].get("alert_on_source_failure", True):
        msg = "\n".join(f"{r.name}: {r.error}" for r in failures)
        notify(cfg, "⚠️ Bike watcher: source failed", msg, tags="warning", priority=3)
    if not matches and cfg["notify"].get("quiet_nothing_new"):
        notify(cfg, "Bike watcher", "Nothing new today.", tags="zzz", priority=1)
    if len(failures) < len(results):     # at least one source worked → today's run counts
        seen["last_run_date"] = melbourne_today(cfg).isoformat()
    save_seen(seen)
    log.info("Done: %d new match(es), %d source failure(s).", len(matches), len(failures))
    return 0 if delivered_all and not failures else 1


def report_source(r: SourceResult):
    if not r.ok:
        log.info("  FAILED: %s", r.error)
        if r.search_url:
            log.info("  page: %s", r.search_url)
        return
    log.info("  search: %s", r.search_url)
    log.info("  %d listing(s) on the results page, %d not seen before, %d opened", r.found, r.new, r.checked)
    for m in r.matches:
        log.info("  MATCH   %s | %s | %s | %s | %s", m.title[:70], m.price, m.location or "?", " ".join(m.labels), m.url)
    for m in r.rejected:
        log.info("  skip    %s | %s (%s)", m.title[:70], m.reject_reason, m.url)


def melbourne_today(cfg) -> dt.date:
    return dt.datetime.now(ZoneInfo(cfg["schedule"]["timezone"])).date()


def scheduled_should_run(cfg) -> bool:
    """The scheduler fires hourly; actually run once per day, at/after run_at_hour Melbourne time.
    That way a run missed while the computer was asleep happens at the next hour it's awake."""
    now = dt.datetime.now(ZoneInfo(cfg["schedule"]["timezone"]))
    seen = load_seen()
    return now.hour >= int(cfg["schedule"]["run_at_hour"]) and seen.get("last_run_date") != now.date().isoformat()


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------
def python_exe() -> str:
    exe = sys.executable
    if platform.system() == "Windows":
        w = Path(exe).with_name("pythonw.exe")   # no console window popping up
        if w.exists():
            return str(w)
    return exe


def install_schedule():
    system = platform.system()
    script = str(HERE / "watcher.py")
    if system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{python_exe()}</string><string>{script}</string><string>--scheduled</string>
  </array>
  <key>WorkingDirectory</key><string>{HERE}</string>
  <key>StartCalendarInterval</key><dict><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>{HERE / 'launchd.out.log'}</string>
  <key>StandardErrorPath</key><string>{HERE / 'launchd.err.log'}</string>
</dict></plist>
""")
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=True)
        print(f"Installed launchd job {plist}")
    elif system == "Windows":
        cmd = f'"{python_exe()}" "{script}" --scheduled'
        subprocess.run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "HOURLY", "/ST", "00:00",
                        "/TR", cmd], check=True)
        print(f"Installed Task Scheduler task '{TASK_NAME}'")
    else:
        if not shutil.which("crontab"):
            raise SystemExit("cron isn't installed. Install it (e.g. sudo apt install cron) or use a systemd timer.")
        line = f'0 * * * * cd "{HERE}" && "{python_exe()}" "{script}" --scheduled >/dev/null 2>&1 {CRON_MARKER}'
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        kept = [l for l in current.splitlines() if CRON_MARKER not in l]
        subprocess.run(["crontab", "-"], input="\n".join(kept + [line]) + "\n", text=True, check=True)
        print("Installed cron entry:\n  " + line)
    print("\nIt checks hourly and runs once a day at the first check at/after 7:00 am Melbourne time.\n"
          "The computer must be ON and AWAKE for it to run. If it was asleep at 7, it runs at the\n"
          "first full hour it's awake (e.g. 8:00), so a missed morning is caught up the same day.")


def uninstall_schedule():
    system = platform.system()
    if system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
    elif system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    else:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        kept = [l for l in current.splitlines() if CRON_MARKER not in l]
        subprocess.run(["crontab", "-"], input="\n".join(kept) + ("\n" if kept else ""), text=True, check=True)
    print("Schedule removed. The watcher will no longer run automatically.")


# --------------------------------------------------------------------------
def setup_logging(verbose: bool, console: bool = True):
    log.setLevel(logging.DEBUG)
    fh = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(message)s"))
        ch.setLevel(logging.DEBUG if verbose else logging.INFO)
        log.addHandler(ch)


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="search and print results; send nothing, remember nothing")
    ap.add_argument("--scheduled", action="store_true", help="used by the scheduler: run only once per day after 7am")
    ap.add_argument("--source", action="append", choices=[k for k, _, _ in SOURCES], help="only check this source")
    ap.add_argument("--test-notify", action="store_true", help="send a test notification and exit")
    ap.add_argument("--install-schedule", action="store_true")
    ap.add_argument("--uninstall-schedule", action="store_true")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    setup_logging(a.verbose)
    cfg = load_config(Path(a.config))
    if a.install_schedule:
        install_schedule()
        return 0
    if a.uninstall_schedule:
        uninstall_schedule()
        return 0
    if a.test_notify:
        ok = notify(cfg, "🚲 Bike watcher test", "If you can read this, notifications work.",
                    click="https://ntfy.sh", tags="white_check_mark")
        print("sent" if ok else "FAILED - see messages above")
        return 0 if ok else 1
    if a.scheduled and not scheduled_should_run(cfg):
        return 0
    log.info("Trek Domane watcher - %s", dt.datetime.now(ZoneInfo(cfg["schedule"]["timezone"])).strftime("%a %d %b %Y %H:%M %Z"))
    return run(cfg, dry_run=a.dry_run, only=a.source)


if __name__ == "__main__":
    sys.exit(main())
