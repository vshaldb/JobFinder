"""
Rippling ATS Careers Fetcher
Fetches job postings from Rippling ATS-powered career boards using the public board API.
Endpoint: https://ats.rippling.com/api/v1/board/{board_slug}/jobs
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

RIPPLING_HEADERS = {
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
    "gurgaon": ["gurgaon", "gurugram"],
    "gurugram": ["gurgaon", "gurugram"],
}


def build_api_url(company: dict) -> str:
    """Construct Rippling board jobs endpoint."""
    slug = (
        company.get("board_slug")
        or company.get("slug")
        or company.get("subdomain")
        or company.get("tenant")
        or company.get("name", "").lower().replace(" ", "")
    )
    return f"https://ats.rippling.com/api/v1/board/{slug}/jobs"


def parse_iso_date(date_str: str) -> tuple[str, Optional[int]]:
    """Parse ISO date string and return (posted_on_str, posted_days_ago)."""
    if not date_str:
        return "", None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_ago = max(0, (now - dt).days)
        return dt.strftime("%Y-%m-%d"), days_ago
    except Exception as e:
        logger.debug(f"Could not parse date '{date_str}': {e}")
        return date_str[:10] if len(date_str) >= 10 else date_str, None


def matches_keyword(title: str, keyword: str) -> bool:
    """Check if the title matches search keyword(s)."""
    if not keyword:
        return True
    return keyword.lower() in title.lower()


def matches_location(job_location: str, target_location: str) -> bool:
    """Check if the job location matches the target location filter."""
    if not target_location:
        return True

    job_loc_lower = job_location.lower()
    target_loc_lower = target_location.lower().strip()

    # Exact or substring match
    if target_loc_lower in job_loc_lower:
        return True

    # Synonym match
    synonyms = LOCATION_SYNONYMS.get(target_loc_lower, [])
    for syn in synonyms:
        if syn in job_loc_lower:
            return True

    return False


def fetch_job_detail(slug: str, job_uuid: str, session: requests.Session) -> dict:
    """Fetch additional details (e.g. createdOn, description) for a single Rippling job."""
    url = f"https://ats.rippling.com/api/v1/board/{slug}/jobs/{job_uuid}"
    try:
        r = session.get(url, headers=RIPPLING_HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug(f"Failed to fetch job detail for {job_uuid}: {e}")
    return {}


def normalize_job(
    raw: dict,
    company: dict,
    filters: dict,
    detail: Optional[dict] = None,
) -> dict:
    """Normalize Rippling job schema to standardized JobFinder schema."""
    slug = (
        company.get("board_slug")
        or company.get("slug")
        or company.get("subdomain")
        or company.get("tenant")
        or company.get("name", "").lower().replace(" ", "")
    )
    job_uuid = raw.get("uuid") or raw.get("id", "")
    title = raw.get("name", "").strip()

    # Location
    work_loc = raw.get("workLocation") or {}
    location_name = work_loc.get("label", "") if isinstance(work_loc, dict) else str(work_loc)

    # Department
    dept_obj = raw.get("department") or {}
    dept_name = dept_obj.get("label") or dept_obj.get("name", "") if isinstance(dept_obj, dict) else str(dept_obj)

    # Detail enrichment if available
    detail_data = detail or {}
    created_on = detail_data.get("createdOn", "")
    posted_on_str, posted_days_ago = parse_iso_date(created_on) if created_on else ("", None)

    emp_type_obj = detail_data.get("employmentType") or {}
    emp_type = emp_type_obj.get("label") or emp_type_obj.get("id", "") if isinstance(emp_type_obj, dict) else str(emp_type_obj)
    final_type = emp_type or dept_name

    job_url = raw.get("url") or f"https://ats.rippling.com/{slug}/jobs/{job_uuid}"
    external_path = f"/jobs/{job_uuid}"

    remote_type = ""
    loc_lower = location_name.lower()
    if "remote" in loc_lower:
        remote_type = "Remote"
    elif "hybrid" in loc_lower:
        remote_type = "Hybrid"
    elif "onsite" in loc_lower or "on-site" in loc_lower:
        remote_type = "Onsite"

    raw_uuid = str(job_uuid or "")
    code_id = str(detail_data.get("code") or detail_data.get("requisitionId") or raw.get("code") or "").strip()
    if code_id:
        job_id = code_id
    elif len(raw_uuid) == 36 and "-" in raw_uuid:
        job_id = raw_uuid[:8]
    else:
        job_id = raw_uuid

    return {
        "company": company["name"],
        "title": title,
        "job_id": job_id,
        "job_id_full": raw_uuid,
        "location": location_name,
        "employment_type": final_type,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": external_path,
        "remote_type": remote_type,
        "source_ats": "rippling",
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
    Fetch all active jobs for a company from Rippling ATS.
    """
    api_url = build_api_url(company)
    slug = (
        company.get("board_slug")
        or company.get("slug")
        or company.get("subdomain")
        or company.get("tenant")
        or company.get("name", "").lower().replace(" ", "")
    )

    logger.info(f"Fetching jobs from {company['name']} (Rippling) → {api_url}")

    keyword_filter = filters.get("keyword", "")
    location_filter = filters.get("location", "")

    try:
        resp = session.get(api_url, headers=RIPPLING_HEADERS, timeout=25)
        resp.raise_for_status()
        raw_jobs = resp.json()
        if not isinstance(raw_jobs, list):
            raw_jobs = raw_jobs.get("jobs", []) or raw_jobs.get("items", []) or []
    except requests.exceptions.RequestException as e:
        err = f"Request error fetching Rippling jobs: {e}"
        logger.error(f"{company['name']}: {err}")
        return {
            "company": company["name"],
            "success": False,
            "error": err,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    total_available = len(raw_jobs)
    matched_jobs: List[dict] = []

    for raw in raw_jobs:
        title = raw.get("name", "").strip()
        if not title:
            continue

        work_loc = raw.get("workLocation") or {}
        location_name = work_loc.get("label", "") if isinstance(work_loc, dict) else str(work_loc)

        if not matches_keyword(title, keyword_filter):
            continue

        if not matches_location(location_name, location_filter):
            continue

        job_uuid = raw.get("uuid") or raw.get("id", "")
        # Fetch detail for createdOn timestamp and full employment type
        detail = fetch_job_detail(slug, job_uuid, session) if job_uuid else {}

        posted_days_ago = None
        if detail.get("createdOn"):
            _, posted_days_ago = parse_iso_date(detail["createdOn"])

        if posted_within_days is not None:
            if posted_days_ago is not None and posted_days_ago > posted_within_days:
                continue

        job_entry = normalize_job(raw, company, filters, detail=detail)
        matched_jobs.append(job_entry)

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

