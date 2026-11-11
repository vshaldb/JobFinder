"""
Oracle Cloud HCM Recruiting Fetcher
Fetches job postings from Oracle Cloud Candidate Experience portals
(e.g. Texas Instruments, Onsemi).
Endpoint: https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

ORACLE_HEADERS = {
    "Accept": "application/json",
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
        "ahmedabad",
        "delhi",
    ],
    "bangalore": ["bangalore", "bengaluru"],
    "bengaluru": ["bangalore", "bengaluru"],
    "gurgaon": ["gurugram", "gurgaon"],
    "gurugram": ["gurugram", "gurgaon"],
}

PAGE_SIZE = 25
MAX_PAGES = 50


def parse_oracle_date(date_str: str) -> Tuple[str, Optional[int]]:
    """Parse ISO YYYY-MM-DD date string and return (posted_on_str, posted_days_ago)."""
    if not date_str:
        return "", None
    clean = str(date_str).strip()[:10]
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = max(0, (now - dt).days)
        return clean, days_ago
    except Exception as e:
        logger.debug(f"Could not parse Oracle HCM date '{date_str}': {e}")
        return clean, None


def resolve_location_facet_id(facets: List[dict], target_location: str) -> Optional[str]:
    """Find best matching Oracle location facet ID for target_location."""
    if not target_location or not facets:
        return None

    target_clean = target_location.lower().strip()
    synonyms = LOCATION_SYNONYMS.get(target_clean, [target_clean])

    # 1. Exact name match (e.g. "India")
    for fac in facets:
        name = str(fac.get("Name") or "").strip().lower()
        if name == target_clean:
            return str(fac.get("Id"))

    # 2. Substring / synonym match, preferring shorter descriptor or highest count
    matches = []
    for fac in facets:
        name = str(fac.get("Name") or "").strip().lower()
        if target_clean in name or any(syn in name for syn in synonyms):
            matches.append((int(fac.get("TotalCount") or 0), -len(name), str(fac.get("Id"))))

    if matches:
        matches.sort(reverse=True)
        return matches[0][2]

    return None


def matches_location(job_loc: str, target_location: str) -> bool:
    """Check if job location matches target location filter."""
    if not target_location:
        return True
    target_clean = target_location.lower().strip()
    synonyms = LOCATION_SYNONYMS.get(target_clean, [target_clean])
    loc_lower = (job_loc or "").lower()
    return target_clean in loc_lower or any(syn in loc_lower for syn in synonyms)


def matches_keyword(title: str, keyword: str) -> bool:
    """Check if job title matches target keyword filter."""
    if not keyword:
        return True
    title_lower = title.lower()
    kw_lower = keyword.lower().strip()
    if kw_lower in title_lower:
        return True
    words = kw_lower.split()
    return any(w in title_lower for w in words)


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize an Oracle Cloud HCM requisition into JobFinder schema."""
    host = company["host"].rstrip("/")
    site_number = company.get("site_number", "CX")
    job_id = str(raw.get("Id") or "").strip()

    job_url_prefix = company.get("job_url_prefix")
    if job_url_prefix:
        job_url = f"{job_url_prefix.rstrip('/')}/{job_id}"
    else:
        job_url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site_number}/job/{job_id}"

    posted_on, posted_days_ago = parse_oracle_date(raw.get("PostedDate") or "")

    emp_type = (
        raw.get("ContractType")
        or raw.get("JobSchedule")
        or raw.get("JobType")
        or raw.get("WorkerType")
        or ""
    )

    primary_loc = str(raw.get("PrimaryLocation") or "").strip()

    return {
        "company": company["name"],
        "title": str(raw.get("Title") or "").strip(),
        "job_id": job_id,
        "location": primary_loc,
        "employment_type": str(emp_type).strip() if emp_type else "",
        "posted_on": posted_on,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/en/sites/{site_number}/job/{job_id}",
        "remote_type": str(raw.get("WorkplaceType") or "").strip(),
        "source_ats": "oracle_hcm",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_filters_applied": filters,
    }


def _fetch_page(
    session: requests.Session,
    api_url: str,
    site_number: str,
    offset: int,
    location_id: Optional[str] = None,
) -> dict:
    """Fetch a single page from Oracle Cloud recruitingCEJobRequisitions."""
    finder_parts = [
        f"siteNumber={site_number}",
        "facetsList=LOCATIONS;POSTING_DATES",
        f"limit={PAGE_SIZE}",
        f"offset={offset}",
    ]
    if location_id:
        finder_parts.append(f"locationId={location_id}")

    params = {
        "onlyData": "true",
        "expand": "requisitionList.secondaryLocations,flexFieldsFacet.values",
        "finder": f"findReqs;{','.join(finder_parts)}",
    }
    resp = session.get(api_url, params=params, headers=ORACLE_HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.json()


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """Fetch matching jobs from an Oracle Cloud HCM Candidate Experience portal."""
    host = company["host"].rstrip("/")
    site_number = company.get("site_number", "CX")
    api_url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    keyword_filter = filters.get("keyword", "")
    location_filter = (filters.get("location") or "").strip()

    logger.info(f"Fetching jobs from {company['name']} (Oracle HCM: {host}/{site_number})")

    try:
        initial_data = _fetch_page(session, api_url, site_number, offset=0)
    except requests.exceptions.RequestException as e:
        err = f"Request failed: {e}"
        logger.error(f"{company['name']}: {err}")
        return {
            "company": company["name"],
            "success": False,
            "error": err,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    items = initial_data.get("items") or []
    first_block = items[0] if items else {}
    locations_facet = first_block.get("locationsFacet") or []

    location_id = company.get("default_location_id") if location_filter.lower() == "india" else None
    if location_filter and not location_id:
        location_id = resolve_location_facet_id(locations_facet, location_filter)

    if location_id:
        try:
            current_data = _fetch_page(
                session, api_url, site_number, offset=0, location_id=location_id
            )
            items = current_data.get("items") or []
            first_block = items[0] if items else {}
        except requests.exceptions.RequestException as e:
            err = f"Location-filtered request failed: {e}"
            logger.error(f"{company['name']}: {err}")
            return {
                "company": company["name"],
                "success": False,
                "error": err,
                "total_available": 0,
                "jobs_fetched": 0,
                "jobs": [],
            }

    total_available = int(first_block.get("TotalJobsCount") or 0)
    matched_jobs: List[dict] = []
    offset = 0
    page = 0

    while page < MAX_PAGES:
        if page > 0:
            try:
                page_data = _fetch_page(
                    session, api_url, site_number, offset=offset, location_id=location_id
                )
                page_items = page_data.get("items") or []
                first_block = page_items[0] if page_items else {}
            except requests.exceptions.RequestException as e:
                logger.warning(f"{company['name']}: Pagination failed at offset {offset}: {e}")
                break

        reqs = first_block.get("requisitionList") or []
        if not reqs:
            break

        for raw in reqs:
            job = normalize_job(raw, company, filters)
            if not job["title"]:
                continue
            if not matches_keyword(job["title"], keyword_filter):
                continue
            if not location_id and not matches_location(job["location"], location_filter):
                continue
            if posted_within_days is not None and posted_within_days > 0:
                if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                    continue

            matched_jobs.append(job)
            if max_jobs and len(matched_jobs) >= max_jobs:
                break

        if max_jobs and len(matched_jobs) >= max_jobs:
            break

        offset += len(reqs)
        if offset >= total_available or len(reqs) < PAGE_SIZE:
            break
        page += 1

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available,
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }

