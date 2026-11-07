"""
Ashby Careers Fetcher
Fetches job postings from Ashby-powered job boards using the public posting API.
Endpoint: https://api.ashbyhq.com/posting-api/job-board/{board_token}
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

ASHBY_HEADERS = {
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
    """Construct Ashby jobs endpoint."""
    board_token = (
        company.get("board_token")
        or company.get("board_slug")
        or company.get("tenant")
        or company.get("name", "").lower().replace(" ", "")
    )
    return f"https://api.ashbyhq.com/posting-api/job-board/{board_token}"


def parse_ashby_date(date_str: str) -> tuple[str, Optional[int]]:
    """Parse ISO date string and return (posted_on_str, posted_days_ago)."""
    if not date_str:
        return "", None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = max(0, (now - dt).days)
        posted_on_str = dt.strftime("%Y-%m-%d")
        return posted_on_str, days_ago
    except Exception as e:
        logger.debug(f"Could not parse Ashby date '{date_str}': {e}")
        return date_str[:10] if len(date_str) >= 10 else date_str, None


def get_all_locations(raw: dict) -> List[str]:
    """Collect all location strings from primary and secondary locations."""
    locs = []
    primary = raw.get("location")
    if primary:
        locs.append(str(primary).strip())

    for sec in raw.get("secondaryLocations", []):
        if isinstance(sec, dict):
            sec_loc = sec.get("location")
            if sec_loc:
                locs.append(str(sec_loc).strip())
            addr = sec.get("address", {})
            if isinstance(addr, dict):
                postal = addr.get("postalAddress", {})
                country = postal.get("addressCountry")
                city = postal.get("addressLocality")
                if city and country:
                    locs.append(f"{city}, {country}")
                elif country:
                    locs.append(country)
        elif isinstance(sec, str):
            locs.append(sec.strip())

    addr = raw.get("address", {})
    if isinstance(addr, dict):
        postal = addr.get("postalAddress", {})
        country = postal.get("addressCountry")
        city = postal.get("addressLocality")
        if city and country:
            locs.append(f"{city}, {country}")
        elif country:
            locs.append(country)

    return list(dict.fromkeys(locs))  # deduplicate preserving order


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
    """Normalize Ashby job schema to standardized JobFinder schema."""
    all_locs = get_all_locations(raw)
    target_loc = (filters.get("location") or "").lower().strip()

    # Determine best display location: prefer one matching the target filter
    display_location = raw.get("location") or ""
    if target_loc and all_locs:
        synonyms = LOCATION_SYNONYMS.get(target_loc, [target_loc])
        for loc in all_locs:
            loc_l = loc.lower()
            if target_loc in loc_l or any(s in loc_l for s in synonyms):
                display_location = loc
                break

    if not display_location and all_locs:
        display_location = ", ".join(all_locs[:2])

    published_at = raw.get("publishedAt") or ""
    posted_on_str, posted_days_ago = parse_ashby_date(published_at)

    raw_id = str(raw.get("id") or "")
    custom_req = str(raw.get("customRequisitionId") or raw.get("requisitionId") or "").strip()
    if custom_req:
        job_id = custom_req
    elif len(raw_id) == 36 and "-" in raw_id:
        job_id = raw_id[:8]
    else:
        job_id = raw_id
    job_url = raw.get("jobUrl") or raw.get("applyUrl") or ""

    dept = raw.get("department") or raw.get("team") or ""
    emp_type = raw.get("employmentType") or ""
    type_info = f"{emp_type} - {dept}".strip(" -") if emp_type else dept

    workplace = raw.get("workplaceType") or ""
    if raw.get("isRemote") and not workplace:
        workplace = "Remote"

    return {
        "company": company["name"],
        "title": (raw.get("title") or "").strip(),
        "job_id": job_id,
        "job_id_full": raw_id,
        "location": display_location,
        "employment_type": type_info,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/jobs/{job_id}",
        "remote_type": workplace,
        "source_ats": "ashby",
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
    Fetch and filter jobs for an Ashby company.

    Returns:
        dict: Standardized fetch result dictionary.
    """
    api_url = build_api_url(company)
    logger.info(f"Fetching Ashby jobs: {company['name']} -> {api_url}")

    try:
        response = session.get(api_url, headers=ASHBY_HEADERS, timeout=15)
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

        data = response.json()
        raw_jobs = data.get("jobs", [])
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

    # Filter to listed jobs only
    listed_jobs = [j for j in raw_jobs if j.get("isListed", True)]
    total_available = len(listed_jobs)

    loc_filter = (filters.get("location") or "").strip()
    kw_filter = (filters.get("keyword") or "").strip()

    filtered_jobs = []
    for raw in listed_jobs:
        if loc_filter and not matches_location(raw, loc_filter):
            continue
        if kw_filter and not matches_keyword(raw.get("title", ""), kw_filter):
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

