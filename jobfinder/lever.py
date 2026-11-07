"""
Lever Careers Fetcher
Fetches job postings from Lever-powered career portals using the public Postings API.
Endpoint: https://api.lever.co/v0/postings/{site_name}?mode=json
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

LEVER_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

LOCATION_SYNONYMS = {
    "india": [
        "india",
        "ind",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "pune",
        "noida",
        "gurgaon",
        "gurugram",
        "chennai",
        "mumbai",
        "ahmedabad",
    ],
    "bangalore": ["bangalore", "bengaluru"],
    "bengaluru": ["bangalore", "bengaluru"],
    "hyderabad": ["hyderabad"],
    "pune": ["pune"],
    "noida": ["noida"],
    "gurugram": ["gurugram", "gurgaon"],
    "gurgaon": ["gurugram", "gurgaon"],
}


def build_api_url(company: dict) -> str:
    """Construct Lever jobs endpoint."""
    site_name = (
        company.get("site_name")
        or company.get("board_token")
        or company.get("board_slug")
        or company.get("tenant")
        or company.get("name", "").lower().replace(" ", "")
    )
    return f"https://api.lever.co/v0/postings/{site_name}?mode=json"


def parse_lever_date(created_at_ms: Optional[int]) -> tuple[str, Optional[int]]:
    """Parse Lever millisecond epoch timestamp and return (posted_on_str, posted_days_ago)."""
    if not created_at_ms:
        return "", None
    try:
        dt = datetime.fromtimestamp(created_at_ms / 1000.0, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = max(0, (now - dt).days)
        posted_on_str = dt.strftime("%Y-%m-%d")
        return posted_on_str, days_ago
    except Exception as e:
        logger.debug(f"Could not parse Lever createdAt '{created_at_ms}': {e}")
        return "", None


def get_all_locations(raw: dict) -> List[str]:
    """Extract all location strings from Lever categories."""
    categories = raw.get("categories", {}) or {}
    locs = []

    loc = categories.get("location")
    if loc:
        locs.append(str(loc).strip())

    all_locs = categories.get("allLocations") or []
    if isinstance(all_locs, list):
        for l in all_locs:
            if l and str(l).strip() not in locs:
                locs.append(str(l).strip())

    country = raw.get("country")
    if country and country not in locs:
        locs.append(str(country).strip())

    return locs


def matches_location(raw: dict, target_location: str) -> bool:
    """Check if any job location matches target location filter."""
    if not target_location:
        return True

    target_clean = target_location.lower().strip()
    synonyms = LOCATION_SYNONYMS.get(target_clean, [target_clean])

    all_locs = get_all_locations(raw)
    for loc in all_locs:
        loc_lower = loc.lower()
        if target_clean in loc_lower:
            return True
        for syn in synonyms:
            if syn in loc_lower:
                return True

    return False


def matches_keyword(job_title: str, target_keyword: str) -> bool:
    """Check if job title matches target keyword filter."""
    if not target_keyword:
        return True
    title_lower = job_title.lower()
    target_lower = target_keyword.lower().strip()
    if target_lower in title_lower:
        return True
    words = target_lower.split()
    return any(w in title_lower for w in words)


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize Lever job schema to standardized JobFinder schema."""
    all_locs = get_all_locations(raw)
    target_loc = (filters.get("location") or "").lower().strip()

    categories = raw.get("categories", {}) or {}
    display_location = categories.get("location") or ""
    if target_loc and all_locs:
        synonyms = LOCATION_SYNONYMS.get(target_loc, [target_loc])
        for loc in all_locs:
            loc_l = loc.lower()
            if target_loc in loc_l or any(s in loc_l for s in synonyms):
                display_location = loc
                break

    if not display_location and all_locs:
        display_location = ", ".join(all_locs[:2])

    created_at = raw.get("createdAt")
    posted_on_str, posted_days_ago = parse_lever_date(created_at)

    raw_id = str(raw.get("id") or "")
    req_code = str(raw.get("reqCode") or "").strip()
    if req_code:
        job_id = req_code
    elif len(raw_id) == 36 and "-" in raw_id:
        job_id = raw_id[:8]
    else:
        job_id = raw_id
    job_url = raw.get("hostedUrl") or raw.get("applyUrl") or ""

    team = categories.get("team") or categories.get("department") or ""
    commitment = categories.get("commitment") or ""
    type_info = f"{commitment} - {team}".strip(" -") if commitment else team

    workplace = raw.get("workplaceType") or ""
    if workplace:
        workplace = workplace.capitalize()

    return {
        "company": company["name"],
        "title": (raw.get("text") or "").strip(),
        "job_id": job_id,
        "job_id_full": raw_id,
        "location": display_location,
        "employment_type": type_info,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/jobs/{job_id}",
        "remote_type": workplace,
        "source_ats": "lever",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_filters_applied": filters,
    }


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Fetch and filter jobs for a Lever company.

    Returns:
        dict: Standardized fetch result dictionary.
    """
    api_url = build_api_url(company)
    logger.info(f"Fetching Lever jobs: {company['name']} -> {api_url}")

    try:
        response = session.get(api_url, headers=LEVER_HEADERS, timeout=15)
        if response.status_code != 200:
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error(f"{company['name']}: {error_msg}")
            return {
                "company": company["name"],
                "success": False,
                "error": error_msg,
                "total_available": 0,
                "jobs_fetched": 0,
                "jobs": [],
            }

        raw_jobs = response.json()
        if not isinstance(raw_jobs, list):
            error_msg = f"Expected list of jobs, got {type(raw_jobs)}"
            logger.error(f"{company['name']}: {error_msg}")
            return {
                "company": company["name"],
                "success": False,
                "error": error_msg,
                "total_available": 0,
                "jobs_fetched": 0,
                "jobs": [],
            }
    except Exception as e:
        error_msg = f"Network or parsing error: {e}"
        logger.error(f"{company['name']}: {error_msg}")
        return {
            "company": company["name"],
            "success": False,
            "error": error_msg,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    total_available = len(raw_jobs)
    loc_filter = (filters.get("location") or "").strip()
    kw_filter = (filters.get("keyword") or "").strip()

    filtered_jobs = []
    for raw in raw_jobs:
        if loc_filter and not matches_location(raw, loc_filter):
            continue
        if kw_filter and not matches_keyword(raw.get("text", ""), kw_filter):
            continue

        normalized = normalize_job(raw, company, filters)

        if posted_within_days is not None:
            days_ago = normalized.get("posted_days_ago")
            if days_ago is not None and days_ago > posted_within_days:
                continue

        filtered_jobs.append(normalized)
        if max_jobs and len(filtered_jobs) >= max_jobs:
            break

    logger.info(f"{company['name']}: {len(filtered_jobs)} matching jobs (out of {total_available})")

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available,
        "jobs_fetched": len(filtered_jobs),
        "jobs": filtered_jobs,
    }

