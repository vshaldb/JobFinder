"""
Greenhouse Careers Fetcher
Fetches job postings from Greenhouse-powered job boards using the public Job Board API.
Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

GREENHOUSE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Synonyms for common location searches (e.g. India tech hubs)
LOCATION_SYNONYMS = {
    "india": ["india", "bengaluru", "bangalore", "hyderabad", "pune", "noida", "gurgaon", "gurugram", "chennai", "mumbai"],
    "bangalore": ["bangalore", "bengaluru"],
    "bengaluru": ["bangalore", "bengaluru"],
}


def build_api_url(company: dict) -> str:
    """Construct Greenhouse jobs endpoint."""
    board_token = company.get("board_token") or company.get("tenant") or company.get("name").lower().replace(" ", "")
    return f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"


def parse_greenhouse_date(date_str: str) -> Optional[int]:
    """Parse ISO date string and return integer days ago."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)
    except Exception as e:
        logger.debug(f"Could not parse date '{date_str}': {e}")
        return None


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize Greenhouse job schema to standardized JobFinder schema."""
    loc_obj = raw.get("location") or {}
    location_name = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)

    date_str = raw.get("first_published") or raw.get("updated_at") or ""
    posted_days_ago = parse_greenhouse_date(date_str)
    posted_on_str = ""
    if date_str:
        try:
            dt = datetime.fromisoformat(date_str)
            posted_on_str = dt.strftime("%Y-%m-%d")
        except Exception:
            posted_on_str = date_str[:10]

    job_id = str(raw.get("id") or raw.get("requisition_id") or "")
    job_url = raw.get("absolute_url", "")

    departments = []
    for dept in raw.get("departments", []):
        if isinstance(dept, dict) and dept.get("name"):
            departments.append(dept["name"])
    dept_str = ", ".join(departments)

    remote_type = ""
    if "remote" in location_name.lower():
        remote_type = "Remote"
    elif "hybrid" in location_name.lower():
        remote_type = "Hybrid"

    return {
        "company": company["name"],
        "title": raw.get("title", ""),
        "job_id": job_id,
        "location": location_name,
        "employment_type": dept_str or raw.get("internal_job_id", ""),
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/jobs/{raw.get('id', '')}",
        "remote_type": remote_type,
        "source_ats": "greenhouse",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_filters_applied": filters,
    }


def matches_location(job_location: str, target_location: str) -> bool:
    """Check if the job location matches the target location filter."""
    if not target_location:
        return True
    
    loc_clean = job_location.lower()
    target_clean = target_location.lower().strip()

    # Direct substring check
    if target_clean in loc_clean:
        return True

    # Check synonyms (e.g. "India" includes "Bengaluru", "Hyderabad")
    synonyms = LOCATION_SYNONYMS.get(target_clean, [])
    for syn in synonyms:
        if syn in loc_clean:
            return True

    return False


def matches_keyword(job_title: str, target_keyword: str) -> bool:
    """Check if the job title matches the keyword query."""
    if not target_keyword:
        return True
    title_lower = job_title.lower()
    target_lower = target_keyword.lower().strip()
    if target_lower in title_lower:
        return True
    words = target_lower.split()
    return any(w in title_lower for w in words)


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Fetch and filter jobs for a Greenhouse company.
    """
    api_url = build_api_url(company)
    logger.info(f"Fetching jobs from {company['name']} (Greenhouse) → {api_url}")

    try:
        response = session.get(
            api_url,
            headers=GREENHOUSE_HEADERS,
            timeout=25,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        logger.error(f"{company['name']}: {error_msg}")
        return {
            "company": company["name"],
            "success": False,
            "error": error_msg,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    try:
        data = response.json()
    except ValueError as e:
        error_msg = f"Failed to parse JSON: {e}"
        logger.error(f"{company['name']}: {error_msg}")
        return {
            "company": company["name"],
            "success": False,
            "error": error_msg,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    raw_jobs = data.get("jobs", [])
    total_available = len(raw_jobs)
    matched_jobs: List[dict] = []

    keyword_filter = filters.get("keyword", "")
    location_filter = filters.get("location", "")

    for raw in raw_jobs:
        job = normalize_job(raw, company, filters)

        # Keyword filter
        if not matches_keyword(job["title"], keyword_filter):
            continue

        # Location filter
        if not matches_location(job["location"], location_filter):
            continue

        # Date filter
        if posted_within_days is not None:
            if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                continue

        matched_jobs.append(job)

        if max_jobs and len(matched_jobs) >= max_jobs:
            break

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available,
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }

