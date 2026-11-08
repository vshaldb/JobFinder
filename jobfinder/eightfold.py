"""
Eightfold.ai Careers Fetcher
Fetches job postings from Eightfold.ai-powered career portals using their public PCSX search API.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

EIGHTFOLD_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

PAGE_LIMIT = 10         # Eightfold typically paginates by 10 items
REQUEST_DELAY = 0.5     # Polite delay between requests
MAX_PAGES = 50          # Up to 500 jobs per company safety cap


def build_search_url(company: dict) -> str:
    """Construct Eightfold.ai search endpoint."""
    if company.get("api_url"):
        return company["api_url"]

    endpoint_type = company.get("search_endpoint", "pcsx")
    host = company.get("host")
    subdomain = company.get("subdomain") or company.get("tenant")

    if host:
        base = f"https://{host}"
    elif subdomain:
        base = f"https://{subdomain}.eightfold.ai"
    else:
        base = "https://eightfold.ai"

    if endpoint_type == "apply_v2":
        return f"{base}/api/apply/v2/jobs"
    return f"{base}/api/pcsx/search"


def build_job_url(company: dict, position_url: str) -> str:
    """Build canonical URL for job details/apply page."""
    if position_url.startswith("http://") or position_url.startswith("https://"):
        return position_url
    
    host = company.get("host")
    if host:
        base_url = f"https://{host}"
    else:
        base_url = company.get("career_site_url")
        if base_url:
            base_url = base_url.split("?")[0].rstrip("/")
            if base_url.endswith("/careers") and position_url.startswith("/careers"):
                base_url = base_url[:-len("/careers")]
        else:
            subdomain = company.get("subdomain") or company.get("tenant")
            base_url = f"https://{subdomain}.eightfold.ai" if subdomain else "https://eightfold.ai"
    
    base = base_url.rstrip("/")
    path = position_url if position_url.startswith("/") else f"/{position_url}"
    return f"{base}{path}"


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize Eightfold position schema to standardized JobFinder schema."""
    position_url = raw.get("canonicalPositionUrl") or raw.get("positionUrl", "")
    job_url = build_job_url(company, position_url) if position_url else ""

    locations = raw.get("locations", [])
    if not locations:
        locations = raw.get("standardizedLocations", [])
    if not locations and raw.get("location"):
        loc_val = raw.get("location")
        locations = [loc_val] if isinstance(loc_val, str) else loc_val
    location_str = ", ".join(locations) if isinstance(locations, list) else str(locations)

    posted_ts = (
        raw.get("postedTs")
        or raw.get("t_create")
        or raw.get("creationTs")
        or raw.get("t_update")
    )
    posted_on_str = ""
    posted_days_ago = None

    if posted_ts:
        try:
            # postedTs is seconds since epoch
            job_dt = datetime.fromtimestamp(posted_ts, tz=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            posted_days_ago = max(0, (now_dt - job_dt).days)
            posted_on_str = job_dt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"Could not parse postedTs {posted_ts}: {e}")

    work_option = raw.get("workLocationOption") or raw.get("work_location_option", "")
    remote_type = ""
    if work_option:
        wo_lower = str(work_option).lower()
        if "remote" in wo_lower:
            remote_type = "Remote"
        elif "hybrid" in wo_lower:
            remote_type = "Hybrid"
        elif "onsite" in wo_lower:
            remote_type = "Onsite"

    job_id = (
        raw.get("displayJobId")
        or raw.get("display_job_id")
        or raw.get("atsJobId")
        or raw.get("ats_job_id")
        or str(raw.get("id", ""))
    )

    return {
        "company": company["name"],
        "title": raw.get("name") or raw.get("posting_name", ""),
        "job_id": job_id,
        "location": location_str,
        "employment_type": work_option or raw.get("department", ""),
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": position_url,
        "remote_type": remote_type,
        "source_ats": "eightfold",
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
    Fetch all (or up to max_jobs) jobs from Eightfold.ai for a single company.
    """
    api_url = build_search_url(company)
    domain_param = (
        company.get("domain_param")
        or company.get("extra_params", {}).get("domain")
        or f"{company.get('subdomain', '')}.com"
    )

    all_jobs: List[dict] = []
    start = 0
    total_available = None
    page = 0

    # Session warmup: Some Eightfold portals (e.g. Microsoft) require initial cookie handshake
    warmup_url = company.get("warmup_url") or company.get("career_site_url")
    if not warmup_url and company.get("host"):
        warmup_url = f"https://{company['host']}/careers"

    if warmup_url:
        try:
            session.get(
                warmup_url,
                headers={
                    "User-Agent": EIGHTFOLD_HEADERS["User-Agent"],
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=15,
            )
        except Exception as e:
            logger.debug(f"{company['name']}: Session warmup exception (continuing): {e}")

    logger.info(f"Fetching jobs from {company['name']} (Eightfold) → {api_url}")

    while True:
        if page >= MAX_PAGES:
            logger.warning(f"{company['name']}: Reached MAX_PAGES ({MAX_PAGES}). Stopping.")
            break

        params = {
            "domain": domain_param,
            "query": filters.get("keyword", ""),
            "location": filters.get("location", ""),
            "start": start,
            "num": PAGE_LIMIT,
        }
        if company.get("extra_params"):
            params.update(company["extra_params"])

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = session.get(
                    api_url,
                    params=params,
                    headers=EIGHTFOLD_HEADERS,
                    timeout=25,
                )
                if response.status_code == 429:
                    sleep_time = (attempt + 1) * 2
                    logger.warning(f"{company['name']}: Rate limited (429). Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                    continue
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    error_msg = str(e)
                    logger.error(f"{company['name']}: {error_msg}")
                    return _error_result(company, error_msg, all_jobs)
                time.sleep((attempt + 1) * 1.5)

        if response is None or response.status_code != 200:
            error_msg = f"HTTP {response.status_code if response else 'No Response'}"
            return _error_result(company, error_msg, all_jobs)

        try:
            raw_json = response.json()
            if isinstance(raw_json, dict) and "data" in raw_json and isinstance(raw_json["data"], dict):
                data = raw_json["data"]
            elif isinstance(raw_json, dict):
                data = raw_json
            else:
                data = {}
        except ValueError as e:
            error_msg = f"Failed to parse JSON: {e}"
            logger.error(f"{company['name']}: {error_msg}")
            return _error_result(company, error_msg, all_jobs)

        if total_available is None:
            total_available = data.get("count", 0)
            logger.info(f"{company['name']}: {total_available} total jobs found on Eightfold")

        positions = data.get("positions", [])
        if not positions:
            break

        for raw in positions:
            job = normalize_job(raw, company, filters)
            if posted_within_days is not None:
                if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                    continue
            all_jobs.append(job)
            if max_jobs and len(all_jobs) >= max_jobs:
                break

        if max_jobs and len(all_jobs) >= max_jobs:
            all_jobs = all_jobs[:max_jobs]
            break

        start += len(positions)
        page += 1

        if total_available is not None and start >= total_available:
            break

        if page > 1:
            time.sleep(REQUEST_DELAY)

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available or len(all_jobs),
        "jobs_fetched": len(all_jobs),
        "jobs": all_jobs,
    }


def _error_result(company: dict, error: str, partial_jobs: list) -> dict:
    return {
        "company": company["name"],
        "success": False,
        "error": error,
        "total_available": 0,
        "jobs_fetched": len(partial_jobs),
        "jobs": partial_jobs,
    }

