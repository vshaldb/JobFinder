"""
Attrax Careers Fetcher
Fetches job postings from Attrax-powered career portals
(e.g. Renesas Electronics at https://jobs.renesas.com).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

ATTRAX_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

LOCATION_SYNONYMS = {
    "india": [
        "india",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "pune",
        "noida",
        "gurgaon",
        "gurugram",
        "chennai",
        "mumbai",
    ],
    "bangalore": ["bengaluru", "bangalore"],
    "bengaluru": ["bengaluru", "bangalore"],
    "gurgaon": ["gurugram", "gurgaon"],
    "gurugram": ["gurugram", "gurgaon"],
}

MAX_PAGES = 100


def parse_attrax_date(date_str: str) -> Tuple[str, Optional[int]]:
    """Parse ISO date string (e.g. '2026-11-06T12:10:20+00:00') cleanly."""
    if not date_str:
        return "", None
    clean = str(date_str).strip()[:10]
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
        return clean, days_ago
    except Exception as e:
        logger.debug(f"Could not parse Attrax date '{date_str}': {e}")
        return clean, None


def matches_location(job_loc: str, target_location: str) -> bool:
    """Check if job location matches target location filter."""
    if not target_location:
        return True
    target_clean = target_location.lower().strip()
    synonyms = LOCATION_SYNONYMS.get(target_clean, [target_clean])
    loc_lower = (job_loc or "").lower()
    return target_clean in loc_lower or any(syn in loc_lower for syn in synonyms)


def matches_keyword(title: str, keyword: str) -> bool:
    """Check if job title matches keyword filter."""
    if not keyword:
        return True
    title_lower = title.lower()
    kw_lower = keyword.lower().strip()
    if kw_lower in title_lower:
        return True
    return any(w in title_lower for w in kw_lower.split())


def _clean_text(raw_html: str) -> str:
    """Strip HTML tags, decode entities, collapse whitespace."""
    no_tags = re.sub(r"<[^>]+>", " ", raw_html)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def _extract_sidebar_options(html_text: str) -> Dict[str, str]:
    """Extract Attrax facet label -> option_id mapping from sidebar checkboxes."""
    options: Dict[str, str] = {}
    for opt_id, label in re.findall(
        r"data-option-id=[\"'](\d+)[\"'][^>]*><span[^>]*aria-label=[\"']([^\"']+)[\"']",
        html_text,
        re.S | re.I,
    ):
        options[html.unescape(label).strip().lower()] = opt_id
    return options


def _resolve_option_ids(options_map: Dict[str, str], target_location: str, job_family: str) -> Tuple[List[str], List[str]]:
    """Resolve Attrax option IDs matching requested location and optional job_family."""
    loc_selected: List[str] = []
    jf_selected: List[str] = []

    if target_location:
        loc_lower = target_location.lower().strip()
        if loc_lower in options_map:
            loc_selected.append(options_map[loc_lower])
        else:
            for syn in LOCATION_SYNONYMS.get(loc_lower, []):
                if syn in options_map:
                    loc_selected.append(options_map[syn])
                    break

    if job_family:
        jf_lower = job_family.lower().strip()
        for label, opt_id in options_map.items():
            if jf_lower in label:
                jf_selected.append(opt_id)
                break

    return loc_selected, jf_selected


def _parse_tiles(html_text: str, base_url: str) -> List[dict]:
    """Parse attrax-vacancy-tile blocks cleanly into intermediate dicts."""
    tile_starts = list(
        re.finditer(
            r'<div[^>]*class=["\'][^"\']*attrax-vacancy-tile\b[^"\']*["\'][^>]*data-jobid=["\'](\d+)["\']',
            html_text,
            re.S | re.I,
        )
    )

    jobs: List[dict] = []
    seen_ids = set()

    for i, m in enumerate(tile_starts):
        job_id = m.group(1).strip()
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        start = m.start()
        end = tile_starts[i + 1].start() if i + 1 < len(tile_starts) else start + 8000
        block = html_text[start:end]

        a_match = re.search(
            r'<a[^>]*class=["\'][^"\']*attrax-vacancy-tile__title[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            block,
            re.S | re.I,
        )
        if not a_match:
            continue
        href, title_raw = a_match.groups()
        title = _clean_text(title_raw)
        if not title:
            continue

        loc_match = re.search(
            r'attrax-vacancy-tile__location-freetext.*?<p[^>]*attrax-vacancy-tile__item-value[^>]*>(.*?)</p>',
            block,
            re.S | re.I,
        )
        location_str = _clean_text(loc_match.group(1)) if loc_match else ""
        if not location_str:
            opt_loc_match = re.search(
                r'attrax-vacancy-tile__option-location\b.*?<p[^>]*attrax-vacancy-tile__item-value[^>]*>(.*?)</p>',
                block,
                re.S | re.I,
            )
            location_str = _clean_text(opt_loc_match.group(1)) if opt_loc_match else ""

        emp_match = re.search(
            r'attrax-vacancy-tile__option-type-of-employment\b.*?<p[^>]*attrax-vacancy-tile__item-value[^>]*>(.*?)</p>',
            block,
            re.S | re.I,
        )
        emp_type = _clean_text(emp_match.group(1)) if emp_match else ""

        remote_match = re.search(
            r'attrax-vacancy-tile__option-remote\b.*?<p[^>]*attrax-vacancy-tile__item-value[^>]*>(.*?)</p>',
            block,
            re.S | re.I,
        )
        remote_val = _clean_text(remote_match.group(1)).lower() if remote_match else ""
        remote_type = "Remote" if remote_val == "yes" else ""

        full_url = f"{base_url}{href}" if href.startswith("/") else href

        jobs.append({
            "title": title,
            "job_id": job_id,
            "location": location_str,
            "employment_type": emp_type or "Full-time",
            "remote_type": remote_type,
            "url": full_url,
            "external_path": href,
        })

    return jobs


def _enrich_posted_dates(jobs: List[dict], session: requests.Session) -> None:
    """Concurrently fetch detail JSON-LD datePosted for matched jobs."""

    def fetch_detail(job: dict) -> None:
        url = job.get("url")
        if not url:
            return
        try:
            resp = session.get(url, headers=ATTRAX_HEADERS, timeout=12)
            if resp.status_code != 200:
                return
            m_date = re.search(r'"datePosted"\s*:\s*"([^"]+)"', resp.text)
            if m_date:
                posted_on, days_ago = parse_attrax_date(m_date.group(1))
                job["posted_on"] = posted_on
                job["posted_days_ago"] = days_ago
        except Exception as e:
            logger.debug(f"Attrax detail fetch failed for {url}: {e}")

    if not jobs:
        return

    with ThreadPoolExecutor(max_workers=min(len(jobs), 8)) as executor:
        list(executor.map(fetch_detail, jobs))


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """Fetch matching jobs from an Attrax careers portal (e.g. Renesas)."""
    base_url = company["career_site_url"].rstrip("/")
    search_url = f"{base_url}/jobs"

    keyword_filter = (filters.get("keyword") or "").strip()
    location_filter = (filters.get("location") or "").strip()
    job_family_filter = (filters.get("job_family") or "").strip()

    logger.info(f"Fetching jobs from {company['name']} (Attrax: {base_url})")

    try:
        init_resp = session.get(search_url, params={"page": "1"}, headers=ATTRAX_HEADERS, timeout=25)
        init_resp.raise_for_status()
        init_html = init_resp.text
    except requests.exceptions.RequestException as e:
        err = f"Initial page request failed: {e}"
        logger.error(f"{company['name']}: {err}")
        return {
            "company": company["name"],
            "success": False,
            "error": err,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    options_map = _extract_sidebar_options(init_html)
    loc_options, jf_options = _resolve_option_ids(options_map, location_filter, job_family_filter)
    selected_options = list(dict.fromkeys(loc_options + jf_options))
    options_param = ",".join(selected_options) if selected_options else ""

    if options_param:
        try:
            page1_resp = session.get(
                search_url,
                params={"options": options_param, "page": "1"},
                headers=ATTRAX_HEADERS,
                timeout=25,
            )
            page1_resp.raise_for_status()
            page1_html = page1_resp.text
        except requests.exceptions.RequestException as e:
            err = f"Filtered page 1 request failed: {e}"
            logger.error(f"{company['name']}: {err}")
            return {
                "company": company["name"],
                "success": False,
                "error": err,
                "total_available": 0,
                "jobs_fetched": 0,
                "jobs": [],
            }
    else:
        page1_html = init_html

    total_match = re.search(r"(\d+)\s+result\(s\)", page1_html, re.I)
    total_available = int(total_match.group(1)) if total_match else 0

    total_pages_match = re.search(
        r"attrax-pagination__results-of--2[^>]*>\s*(\d+)", page1_html, re.S | re.I
    )
    total_pages = min(int(total_pages_match.group(1)) if total_pages_match else 1, MAX_PAGES)

    raw_tiles = _parse_tiles(page1_html, base_url)

    # Fetch remaining pages concurrently when unfiltered on location or when more results needed
    need_more_pages = total_pages > 1 and (
        not max_jobs or posted_within_days or keyword_filter or len(raw_tiles) < max_jobs
    )
    if need_more_pages:
        def fetch_page_html(p: int) -> List[dict]:
            params = {"page": str(p)}
            if options_param:
                params["options"] = options_param
            try:
                r = session.get(search_url, params=params, headers=ATTRAX_HEADERS, timeout=25)
                if r.status_code == 200:
                    return _parse_tiles(r.text, base_url)
            except Exception as e:
                logger.debug(f"Attrax page {p} fetch failed: {e}")
            return []

        pages_to_fetch = list(range(2, total_pages + 1))
        with ThreadPoolExecutor(max_workers=min(len(pages_to_fetch), 6)) as executor:
            for page_tiles in executor.map(fetch_page_html, pages_to_fetch):
                raw_tiles.extend(page_tiles)

    matched_prelim: List[dict] = []
    seen_ids = set()
    used_loc_option = bool(loc_options)

    for raw in raw_tiles:
        jid = raw["job_id"]
        if jid in seen_ids:
            continue
        seen_ids.add(jid)

        if not matches_keyword(raw["title"], keyword_filter):
            continue
        if location_filter and not used_loc_option:
            if not matches_location(raw["location"], location_filter):
                continue

        matched_prelim.append({
            "company": company["name"],
            "title": raw["title"],
            "job_id": jid,
            "location": raw["location"],
            "employment_type": raw["employment_type"],
            "posted_on": "",
            "posted_days_ago": None,
            "url": raw["url"],
            "external_path": raw["external_path"],
            "remote_type": raw["remote_type"],
            "source_ats": "attrax",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "_filters_applied": filters,
        })

    if total_available == 0 or keyword_filter or (location_filter and not used_loc_option):
        total_reported = len(matched_prelim)
    else:
        total_reported = total_available

    if max_jobs and not posted_within_days and len(matched_prelim) > max_jobs:
        matched_prelim = matched_prelim[:max_jobs]

    _enrich_posted_dates(matched_prelim, session)

    final_jobs: List[dict] = []
    for job_item in matched_prelim:
        if posted_within_days is not None and posted_within_days > 0:
            if job_item["posted_days_ago"] is not None and job_item["posted_days_ago"] > posted_within_days:
                continue
        final_jobs.append(job_item)
        if max_jobs and len(final_jobs) >= max_jobs:
            break

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_reported,
        "jobs_fetched": len(final_jobs),
        "jobs": final_jobs,
    }
