"""HYROX results scraper — fetches race results from results.hyrox.com."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from paceforge.hyrox.models import HyroxRaceResult, HyroxSplit

logger = logging.getLogger(__name__)

# Search across multiple seasons to find all historical races
SEASON_URLS = [
    "https://results.hyrox.com/season-5/",  # 22/23
    "https://results.hyrox.com/season-6/",  # 23/24
    "https://results.hyrox.com/season-7/",  # 24/25
    "https://results.hyrox.com/season-8/",  # 25/26
]
BASE_URL = SEASON_URLS[-1]  # Default for detail page fetches
DEFAULT_TIMEOUT = 15

# Division codes (event parameter values)
DIVISIONS = {
    "all": None,
    "hyrox": "H_HYROXOVERALL",
    "hyrox_pro": "HPRO_HYROXOVERALL",
    "hyrox_doubles": "HD_HYROXOVERALL",
    "hyrox_relay": "HR_HYROXOVERALL",
    "hyrox_pro_doubles": "HPROD_HYROXOVERALL",
}

# Mapping from split table labels to our canonical names
_SPLIT_NAME_MAP = {
    "Running 1": "Running_1",
    "Running 2": "Running_2",
    "Running 3": "Running_3",
    "Running 4": "Running_4",
    "Running 5": "Running_5",
    "Running 6": "Running_6",
    "Running 7": "Running_7",
    "Running 8": "Running_8",
    "1000m SkiErg": "SkiErg_1000m",
    "50m Sled Push": "Sled_Push_50m",
    "50m Sled Pull": "Sled_Pull_50m",
    "80m Burpee Broad Jump": "Burpee_Broad_Jump_80m",
    "1000m Row": "Row_1000m",
    "200m Farmers Carry": "Farmers_Carry_200m",
    "100m Sandbag Lunges": "Sandbag_Lunges_100m",
    "Wall Balls": "Wall_Balls",
    "Roxzone Time": "Roxzone_Time",
    # Also handle alternative labels
    "SkiErg": "SkiErg_1000m",
    "Sled Push": "Sled_Push_50m",
    "Sled Pull": "Sled_Pull_50m",
    "Burpee Broad Jump": "Burpee_Broad_Jump_80m",
    "Row": "Row_1000m",
    "Farmers Carry": "Farmers_Carry_200m",
    "Sandbag Lunges": "Sandbag_Lunges_100m",
}


def _time_to_seconds(time_str: str) -> float | None:
    """Convert time string (MM:SS, H:MM:SS, HH:MM:SS, or MM:SS.ss) to seconds."""
    if not time_str or time_str in ("N/A", "–", "-", "&ndash;", "", "00.00"):
        return None
    time_str = time_str.strip()
    # Handle MM:SS.ss format (e.g. "59:06.59")
    match = re.match(r"^(\d+):(\d{2})\.(\d+)$", time_str)
    if match:
        mins, secs, frac = match.groups()
        return int(mins) * 60 + int(secs) + float(f"0.{frac}")
    try:
        parts = time_str.split(":")
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        elif len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        pass
    return None


# Scraped strings are third-party content that later reaches the coach prompt via
# data/hyrox.json — cap and flatten them so a crafted results page cannot smuggle
# multi-line instructions or unbounded text into the athlete's data.
MAX_FIELD_LEN = 80
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")


def _clean(text: str | None, max_len: int = MAX_FIELD_LEN) -> str:
    """Flatten whitespace/control chars and cap length of one scraped field."""
    if not text:
        return ""
    text = _CONTROL_CHARS.sub(" ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _seconds_to_display(secs: float | None) -> str:
    """Convert seconds back to H:MM:SS or M:SS display string."""
    if secs is None:
        return "—"
    total = int(secs)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class HyroxScraper:
    """Scrapes HYROX race results for a specific athlete by name."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _parse_city_date(city_text: str) -> tuple[str, str]:
        """Parse 'Dublin 2025' → ('Dublin', '2025') or ('Dublin', '') if no year."""
        match = re.match(r'^(.+?)\s+(\d{4})$', city_text.strip())
        if match:
            return match.group(1).strip(), match.group(2)
        return city_text.strip(), ""

    def search_preview(
        self,
        name: str,
        *,
        firstname: str = "",
        division: str = "all",
        gender: str = "M",
    ) -> list[dict]:
        """Return listing summaries (no detail fetches) for the user to pick from.

        Each dict has: rank, name, city, total_time, athlete_url, event_date.
        """
        surname, first = self._split_name(name, firstname)
        summaries = self._search_listing(surname, firstname=first, division=division, gender=gender)
        return summaries

    def search_athlete(
        self,
        name: str,
        *,
        firstname: str = "",
        division: str = "all",
        gender: str = "M",
        max_results: int = 30,
        selected_urls: list[str] | None = None,
    ) -> list[HyroxRaceResult]:
        """Search for an athlete by name and return their race results with full splits.

        Args:
            name: Athlete surname or full name to search for.
            firstname: Optional first name for more precise matching.
            division: Division key ('all', 'hyrox', 'hyrox_pro', etc.).
            gender: 'M' or 'F'.
            max_results: Maximum number of race results to fetch details for.
            selected_urls: If provided, only fetch details for these athlete URLs.

        Returns:
            List of HyroxRaceResult with full split data.
        """
        surname, first = self._split_name(name, firstname)
        summaries = self._search_listing(surname, firstname=first, division=division, gender=gender)
        logger.info("Found %d listing results for '%s' / '%s'", len(summaries), surname, first)

        # Filter to user-selected races if provided
        if selected_urls is not None:
            url_set = set(selected_urls)
            summaries = [s for s in summaries if s.get("athlete_url") in url_set]

        # Limit to most recent results
        summaries = summaries[:max_results]

        results: list[HyroxRaceResult] = []
        for i, summary in enumerate(summaries):
            if i > 0:
                time.sleep(0.8)  # Rate limiting between detail page fetches
            try:
                result = self._fetch_detail(summary)
                results.append(result)
            except Exception as e:
                logger.warning("Failed to fetch detail for %s: %s", summary.get("name"), e)
                results.append(HyroxRaceResult(
                    rank=summary.get("rank", ""),
                    name=summary.get("name", ""),
                    city=summary.get("city", ""),
                    event_date=summary.get("city_raw", "") or summary.get("city", ""),
                    total_time_display=summary.get("total_time", ""),
                    total_time_seconds=_time_to_seconds(summary.get("total_time", "")),
                    athlete_url=summary.get("athlete_url", ""),
                ))

        return results

    @staticmethod
    def _split_name(name: str, firstname: str = "") -> tuple[str, str]:
        """Extract (surname, firstname) from user input.

        Supports: "Perez Rodriguez" (surname only), "Victor Perez Rodriguez"
        (first + surname), "Perez Rodriguez, Victor" (surname, first).
        An explicit firstname parameter always wins.
        """
        if firstname:
            return name.strip(), firstname.strip()

        stripped = name.strip()
        if "," in stripped:
            parts = stripped.split(",", 1)
            return parts[0].strip(), parts[1].strip()

        # Heuristic: if 3+ words, first word is likely the first name
        words = stripped.split()
        if len(words) >= 3:
            return " ".join(words[1:]), words[0]

        # 1-2 words: treat as surname only
        return stripped, ""

    def _search_listing(
        self,
        name: str,
        *,
        firstname: str = "",
        division: str = "all",
        gender: str = "M",
    ) -> list[dict]:
        """Fetch the ranking listing page filtered by athlete name.

        Searches across all seasons (5-8) and all divisions to find
        historical races. Results are de-duplicated by athlete_url.
        """
        if division == "all":
            return self._search_all_divisions(name, firstname=firstname, gender=gender)

        seen_urls: set[str] = set()
        all_results: list[dict] = []

        for base_url in SEASON_URLS:
            params: dict[str, str] = {
                "pid": "list_overall",
                "pidp": "ranking_nav",
                "search[name]": name,
                "search[sex]": gender,
            }
            if firstname:
                params["search[firstname]"] = firstname
            event_code = DIVISIONS.get(division)
            if event_code:
                params["event"] = event_code

            try:
                resp = self._client.get(base_url, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Failed to fetch listing from %s: %s", base_url, e)
                continue

            for entry in self._parse_listing(resp.text, base_url=base_url):
                url = entry.get("athlete_url", "")
                if url and url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append(entry)

            time.sleep(0.3)

        return all_results

    def _search_all_divisions(self, name: str, *, firstname: str = "", gender: str = "M") -> list[dict]:
        """Search across all divisions AND all seasons — de-duplicated results."""
        seen_urls: set[str] = set()
        all_results: list[dict] = []

        for base_url in SEASON_URLS:
            for div_key, event_code in DIVISIONS.items():
                if div_key == "all" or event_code is None:
                    continue
                params: dict[str, str] = {
                    "pid": "list_overall",
                    "pidp": "ranking_nav",
                    "search[name]": name,
                    "search[sex]": gender,
                    "event": event_code,
                }
                if firstname:
                    params["search[firstname]"] = firstname
                try:
                    resp = self._client.get(base_url, params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    logger.warning("Failed to fetch %s from %s: %s", div_key, base_url, e)
                    continue

                for entry in self._parse_listing(resp.text, base_url=base_url):
                    url = entry.get("athlete_url", "")
                    if url and url in seen_urls:
                        continue
                    seen_urls.add(url)
                    all_results.append(entry)

                time.sleep(0.3)

        return all_results

    def _parse_listing(self, html: str, *, base_url: str = "") -> list[dict]:
        """Parse athlete summaries from the ranking listing page."""
        soup = BeautifulSoup(html, "lxml")
        athletes: list[dict] = []

        items = soup.find_all("li", class_="list-group-item")
        if not items:
            # Fallback: try finding h4 elements with athlete names
            items = soup.find_all("li", class_=re.compile(r"list-group-item"))

        for item in items:
            try:
                # Extract rank
                rank_elem = item.find("div", class_="type-place")
                rank = _clean(rank_elem.get_text(strip=True) if rank_elem else "")

                # Extract name and link
                name_elem = item.find("h4", class_="type-fullname")
                if not name_elem:
                    continue
                name_link = name_elem.find("a")
                if not name_link:
                    continue
                name = _clean(name_link.get_text(strip=True))
                athlete_url = _clean(name_link.get("href", ""), 500)

                # Extract city/event (contains "Dublin 2025" format)
                fields = item.find_all("div", class_="type-field")
                city_raw = ""
                for f in fields:
                    text = _clean(f.get_text(strip=True))
                    if text.startswith("City"):
                        city_raw = text[4:].strip()
                        break

                # Parse city and date from "Dublin 2025" format
                city_name, event_year = self._parse_city_date(city_raw)

                # Extract total time
                total_time = ""
                pull_right = item.find("div", class_="pull-right")
                if pull_right:
                    time_elem = pull_right.find("div", class_="type-time")
                    if time_elem:
                        time_text = _clean(time_elem.get_text(strip=True))
                        if "Total" in time_text:
                            total_time = time_text.replace("Total", "").strip()
                        else:
                            total_time = time_text

                if not name or name == "Name":
                    continue

                athletes.append({
                    "rank": rank,
                    "name": name,
                    "city": city_name,
                    "city_raw": city_raw,
                    "event_year": event_year,
                    "total_time": total_time,
                    "athlete_url": athlete_url,
                    "base_url": base_url or BASE_URL,
                })
            except Exception as e:
                logger.debug("Error parsing listing item: %s", e)
                continue

        return athletes

    def _fetch_detail(self, summary: dict) -> HyroxRaceResult:
        """Fetch the individual athlete detail page and extract splits."""
        athlete_url = summary.get("athlete_url", "")
        base_url = summary.get("base_url", BASE_URL)
        city = summary.get("city", "")
        event_date = summary.get("city_raw", "") or city

        if not athlete_url:
            return HyroxRaceResult(
                rank=summary.get("rank", ""),
                name=summary.get("name", ""),
                city=city,
                event_date=event_date,
                total_time_display=summary.get("total_time", ""),
                total_time_seconds=_time_to_seconds(summary.get("total_time", "")),
            )

        full_url = urljoin(base_url, athlete_url)
        resp = self._client.get(full_url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        detail = self._parse_detail(soup)

        # Use detail page date if available, otherwise fall back to listing
        detail_date = detail.get("event_date", "")
        if detail_date:
            event_date = detail_date

        return HyroxRaceResult(
            rank=summary.get("rank", ""),
            rank_gender=detail.get("rank_mw", ""),
            rank_age_group=detail.get("rank_ag", ""),
            name=summary.get("name", ""),
            nationality=detail.get("nationality", ""),
            city=city,
            event_date=event_date,
            division=detail.get("division", ""),
            age_group=detail.get("age_group", ""),
            total_time_display=summary.get("total_time", ""),
            total_time_seconds=_time_to_seconds(summary.get("total_time", "")),
            splits=detail.get("splits", []),
            athlete_url=athlete_url,
        )

    def _parse_detail(self, soup: BeautifulSoup) -> dict:
        """Parse the athlete detail page for splits, age group, division, ranks."""
        result: dict = {
            "splits": [],
            "age_group": "",
            "division": "",
            "rank_mw": "",
            "rank_ag": "",
            "nationality": "",
            "event_date": "",
        }

        # Extract nationality from flag image
        flag_img = soup.find("img", src=re.compile(r"flags/"))
        if flag_img:
            result["nationality"] = _clean(flag_img.get("alt", ""))

        # Try to find event date from the page
        # Look for date patterns (DD.MM.YYYY, DD/MM/YYYY, Month DD YYYY, etc.)
        page_text = soup.get_text()
        date_patterns = [
            r'(\d{1,2})[./](\d{1,2})[./](\d{4})',  # DD.MM.YYYY or DD/MM/YYYY
            r'(\d{4})-(\d{2})-(\d{2})',  # YYYY-MM-DD
        ]
        for pat in date_patterns:
            m = re.search(pat, page_text)
            if m:
                groups = m.groups()
                if len(groups[0]) == 4:  # YYYY-MM-DD
                    result["event_date"] = f"{groups[0]}-{groups[1]}-{groups[2]}"
                else:  # DD.MM.YYYY
                    result["event_date"] = f"{groups[2]}-{groups[1].zfill(2)}-{groups[0].zfill(2)}"
                break

        # Extract rank and age group from tables
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = _clean(cells[1].get_text(strip=True))
                    if label == "Rank (M/W)":
                        result["rank_mw"] = value if value not in ("–", "-") else ""
                    elif label == "Rank (AG)":
                        result["rank_ag"] = value if value not in ("–", "-") else ""
                    elif label == "Age Group" or "Age" in label:
                        result["age_group"] = value

        # Extract division
        division_row = soup.find("tr", class_="f-__event")
        if division_row:
            division_cell = division_row.find("td")
            if division_cell:
                result["division"] = _clean(division_cell.get_text(strip=True))

        # Extract workout splits from the splits table
        splits: list[HyroxSplit] = []
        for table in tables:
            headers = table.find_all("th")
            if any("Split" in h.get_text() or "split" in h.get_text().lower() for h in headers):
                rows = table.find_all("tr")[1:]  # Skip header
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        split_label = cells[0].get_text(strip=True)
                        time_value = cells[1].get_text(strip=True)
                        canonical = _SPLIT_NAME_MAP.get(split_label)
                        if canonical:
                            splits.append(HyroxSplit(
                                name=canonical,
                                time_seconds=_time_to_seconds(time_value),
                            ))
                break  # Only process the first splits table

        # Fallback: regex-based extraction if table parsing found nothing
        if not splits:
            splits = self._extract_splits_fallback(soup)

        result["splits"] = splits
        return result

    def _extract_splits_fallback(self, soup: BeautifulSoup) -> list[HyroxSplit]:
        """Fallback: extract splits via regex patterns from page text."""
        splits: list[HyroxSplit] = []
        page_text = soup.get_text()
        patterns = {
            "Running_1": [r"Running\s*1[:\s]*([0-9:]+)"],
            "Running_2": [r"Running\s*2[:\s]*([0-9:]+)"],
            "Running_3": [r"Running\s*3[:\s]*([0-9:]+)"],
            "Running_4": [r"Running\s*4[:\s]*([0-9:]+)"],
            "Running_5": [r"Running\s*5[:\s]*([0-9:]+)"],
            "Running_6": [r"Running\s*6[:\s]*([0-9:]+)"],
            "Running_7": [r"Running\s*7[:\s]*([0-9:]+)"],
            "Running_8": [r"Running\s*8[:\s]*([0-9:]+)"],
            "SkiErg_1000m": [r"1000m\s*SkiErg[:\s]*([0-9:]+)"],
            "Sled_Push_50m": [r"50m\s*Sled\s*Push[:\s]*([0-9:]+)"],
            "Sled_Pull_50m": [r"50m\s*Sled\s*Pull[:\s]*([0-9:]+)"],
            "Burpee_Broad_Jump_80m": [r"80m\s*Burpee\s*Broad\s*Jump[:\s]*([0-9:]+)"],
            "Row_1000m": [r"1000m\s*Row[:\s]*([0-9:]+)"],
            "Farmers_Carry_200m": [r"200m\s*Farmers\s*Carry[:\s]*([0-9:]+)"],
            "Sandbag_Lunges_100m": [r"100m\s*Sandbag\s*Lunges[:\s]*([0-9:]+)"],
            "Wall_Balls": [r"Wall\s*Balls[:\s]*([0-9:]+)"],
            "Roxzone_Time": [r"Roxzone\s*Time[:\s]*([0-9:]+)"],
        }
        for split_name, pats in patterns.items():
            for pat in pats:
                match = re.search(pat, page_text, re.IGNORECASE)
                if match:
                    splits.append(HyroxSplit(
                        name=split_name,
                        time_seconds=_time_to_seconds(match.group(1)),
                    ))
                    break
        return splits


def to_cached_dict(
    results: list[HyroxRaceResult], *, search_name: str, search_gender: str
) -> dict:
    """Wrap scraped results in the persisted shape store.load_hyrox_results reads."""
    return {
        "search_name": search_name,
        "search_gender": search_gender,
        "results": [r.model_dump(mode="json") for r in results],
    }
