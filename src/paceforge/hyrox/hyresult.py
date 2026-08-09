"""HYROX results via hyresult.com.

We previously scraped results.hyrox.com's season *overall* ranking, but that
ranking is combined across every city in the season: it silently omits some
races (e.g. Berlin 2026) and its ranks are season-cumulative, not per-race.
hyresult.com server-renders complete per-race data (every split + its rank in
the field) into its React-Server-Components stream, which we can parse
statically — no JS, no API key. This module is the importer built on it.
"""

from __future__ import annotations

import logging
import re
import time

import httpx

from paceforge.hyrox.models import HyroxRaceResult, HyroxSplit

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hyresult.com"
DEFAULT_TIMEOUT = 20
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_RESULT_ID_RE = re.compile(r"^[A-Z0-9_]+$")
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# hyresult split label -> our canonical name
_SPLIT_NAME_MAP = {
    "Run 1": "Running_1", "Run 2": "Running_2", "Run 3": "Running_3",
    "Run 4": "Running_4", "Run 5": "Running_5", "Run 6": "Running_6",
    "Run 7": "Running_7", "Run 8": "Running_8",
    "SkiErg": "SkiErg_1000m", "Sled Push": "Sled_Push_50m",
    "Sled Pull": "Sled_Pull_50m", "Burpee Broad Jump": "Burpee_Broad_Jump_80m",
    "Row": "Row_1000m", "Farmers Carry": "Farmers_Carry_200m",
    "Sandbag Lunges": "Sandbag_Lunges_100m", "Wall Balls": "Wall_Balls",
    "Roxzone": "Roxzone_Time",
}


def _seconds_to_display(secs: float | None) -> str:
    if secs is None:
        return "—"
    total = int(secs)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _rsc_blob(html: str) -> str:
    """Concatenate and unescape the Next.js RSC streaming chunks."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    return "".join(chunks).encode().decode("unicode_escape", "ignore")


def _first(pattern: str, blob: str) -> str:
    m = re.search(pattern, blob)
    return m.group(1) if m else ""


class HyresultScraper:
    """Fetches an athlete's complete HYROX history from hyresult.com."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": _UA}, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def result_ids(self, slug: str) -> list[str]:
        """Return all race result IDs from an athlete profile slug."""
        if not _SLUG_RE.match(slug):
            raise ValueError(f"invalid hyresult athlete slug: {slug!r}")
        resp = self._client.get(f"{BASE_URL}/athlete/{slug}")
        resp.raise_for_status()
        blob = _rsc_blob(resp.text)
        # De-dupe preserving order.
        seen: dict[str, None] = {}
        for rid in re.findall(r"/result/([A-Z0-9_]+)", blob):
            seen.setdefault(rid, None)
        return list(seen)

    def fetch_result(self, result_id: str) -> HyroxRaceResult:
        """Fetch and parse one /result/<id> page into a HyroxRaceResult."""
        if not _RESULT_ID_RE.match(result_id):
            raise ValueError(f"invalid hyresult result id: {result_id!r}")
        resp = self._client.get(f"{BASE_URL}/result/{result_id}")
        resp.raise_for_status()
        return parse_result(resp.text, result_id)

    def fetch_athlete(self, slug: str) -> list[HyroxRaceResult]:
        """Fetch every race for an athlete profile slug."""
        results: list[HyroxRaceResult] = []
        for i, rid in enumerate(self.result_ids(slug)):
            if i > 0:
                time.sleep(0.5)
            try:
                results.append(self.fetch_result(rid))
            except Exception as e:  # noqa: BLE001 - keep importing the rest
                logger.warning("Failed to fetch hyresult %s: %s", rid, e)
        return results


def parse_result(html: str, result_id: str = "") -> HyroxRaceResult:
    """Parse a hyresult /result page's HTML into a HyroxRaceResult."""
    blob = _rsc_blob(html)

    splits: list[HyroxSplit] = []
    # Each segment: {"name":..,"time":int,"rank":int,"num_idps":int,..,"station":".."}
    for obj in re.findall(r'\{[^{}]*"station":"[^"]+"[^{}]*\}', blob):
        name = _first(r'"name":"([^"]+)"', obj)
        canonical = _SPLIT_NAME_MAP.get(name)
        if not canonical:
            continue  # skip the Runs/Workouts roll-up rows
        t = _first(r'"time":(\d+)', obj)
        splits.append(HyroxSplit(
            name=canonical,
            time_seconds=float(t) if t else None,
            rank=_first(r'"rank":(\d+)', obj),
            field_size=_first(r'"num_idps":(\d+)', obj),
        ))

    # Total Time carries a nested object, so grab it from its own window.
    total_win = blob[blob.find('"name":"Total Time"'):][:160]
    total_t = _first(r'"time":(\d+)', total_win)
    total_seconds = float(total_t) if total_t else None
    gender_rank = _first(r'"rank":(\d+)', total_win)
    field_size = _first(r'"num_idps":(\d+)', total_win)

    # The header renders two rank badges: overall (men's field) then "#N in AG".
    age_rank = _first(r'\["#",(\d+)\][^\[]*"in AG"', blob)

    # Header metadata (city + year live in the ranking slug, e.g. s8-2026-berlin-hyrox-men).
    slug_city = _first(r'/ranking/s\d-\d{4}-([a-z-]+?)-hyrox', blob)
    city = slug_city.replace("-", " ").title()
    season_year = _first(r'/ranking/s\d-(\d{4})-', blob)
    division = _first(r'"division":"([^"]+)"', blob)
    age_group = _first(r'"age_group":"([^"]+)"', blob) or _first(r"MEN (\d{2}-\d{2})", blob)
    nationality = _first(r"/flags/([a-z]{2})\.svg", blob)

    return HyroxRaceResult(
        rank=gender_rank,          # overall placement in the gender field
        rank_gender=gender_rank,
        rank_age_group=age_rank,
        field_size=field_size,
        name=_first(r'"athlete_name":"([^"]+)"', blob),
        nationality=nationality.upper(),
        city=city,
        event_date=f"{city} {season_year}".strip() if city else season_year,
        division=division or "HYROX",
        age_group=age_group,
        total_time_seconds=total_seconds,
        total_time_display=_seconds_to_display(total_seconds),
        splits=splits,
        athlete_url=f"{BASE_URL}/result/{result_id}",
    )
