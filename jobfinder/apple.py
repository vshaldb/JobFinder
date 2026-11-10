"""
Apple Jobs Fetcher
Fetches job postings from Apple Careers (jobs.apple.com) API.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

APPLE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://jobs.apple.com/en-in/search?location=india-INDC",
}

PAGE_SIZE = 20
REQUEST_DELAY = 0.5
MAX_PAGES = 50


def normalize_job(raw: dict, company: dict, filters: dict, locale: str = "en-in") -> dict:
    """Normalize Apple job item to standardized JobFinder schema."""
    position_id = str(raw.get("positionId") or raw.get("id") or raw.get("reqId", ""))
    title = raw.get("postingTitle", "Untitled Position")
    transformed_title = raw.get("transformedPostingTitle", "")

    locations: List[str] = []
    for loc in raw.get("locations", []):
        if isinstance(loc, dict):
            city = loc.get("city")
            state = loc.get("stateProvince")
            country = loc.get("countryName")
            parts = [p for p in (city, state, country) if p]
            if parts:
                locations.append(", ".join(parts))
        elif isinstance(loc, str):
            locations.append(loc)
    location_str = " | ".join(locations) if locations else "Not specified"

    team = raw.get("team", {})
    emp_type = team.get("teamName", "") if isinstance(team, dict) else str(team)

    posted_on_str = ""
    posted_days_ago = None
    post_date_gmt = raw.get("postDateInGMT")

    if post_date_gmt and isinstance(post_date_gmt, str):
        try:
            # ISO timestamp string e.g. 2026-11-08T19:05:36.722226134Z
            iso_clean = post_date_gmt[:19] + "+00:00"
            job_dt = datetime.fromisoformat(iso_clean)
            now_dt = datetime.now(timezone.utc)
            posted_days_ago = max(0, (now_dt - job_dt).days)
            posted_on_str = job_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    if not posted_on_str and raw.get("postingDate"):
        try:
            # e.g. "08 Nov 2026"
            dt = datetime.strptime(raw["postingDate"].strip(), "%d %b %Y").replace(tzinfo=timezone.utc)
            posted_days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
            posted_on_str = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    remote_type = "Remote" if raw.get("homeOffice") else "Onsite"

    if transformed_title:
        job_url = f"https://jobs.apple.com/{locale}/details/{position_id}/{transformed_title}"
    else:
        job_url = f"https://jobs.apple.com/{locale}/details/{position_id}"

    return {
        "company": company["name"],
        "title": title,
        "job_id": position_id,
        "location": location_str,
        "employment_type": emp_type,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/{locale}/details/{position_id}",
        "remote_type": remote_type,
        "source_ats": "apple",
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
    """Fetch jobs from Apple Careers API."""
    locale = company.get("locale", "en-in")
    logger.info(f"Fetching jobs from {company['name']} (Apple Careers) [locale: {locale}]")

    # 1. Fetch CSRF token
    csrf_url = "https://jobs.apple.com/api/v1/CSRFToken"
    try:
        r_token = session.get(csrf_url, headers=APPLE_HEADERS, timeout=15)
        csrf_token = r_token.headers.get("x-apple-csrf-token")
        if not csrf_token:
            csrf_token = r_token.text.strip()
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to obtain Apple CSRF token: {e}"
        logger.error(f"{company['name']}: {error_msg}")
        return _error_result(company, error_msg, [])

    search_url = "https://jobs.apple.com/api/v1/search"
    search_headers = dict(APPLE_HEADERS)
    search_headers["X-Apple-CSRF-Token"] = csrf_token
    search_headers["Content-Type"] = "application/json"

    # Location filter code
    loc_filter = filters.get("location", "").strip().lower()
    locations_payload: List[str] = []
    if loc_filter:
        if loc_filter in ("india", "in", "ind"):
            locations_payload = [company.get("location_code", "postLocation-INDC")]
        else:
            locations_payload = [f"postLocation-{filters['location'].strip()}"]
    elif company.get("location_code"):
        locations_payload = [company["location_code"]]

    keyword = filters.get("keyword", "")

    all_jobs: List[dict] = []
    page = 1
    total_available = None

    while True:
        if page > MAX_PAGES:
            logger.warning(f"{company['name']}: Reached MAX_PAGES ({MAX_PAGES}). Stopping.")
            break

        payload = {
            "query": keyword,
            "filters": {
                "locations": locations_payload,
            },
            "page": page,
            "locale": locale,
            "sort": "relevance",
            "format": {
                "longDate": "MMMM D, YYYY",
                "mediumDate": "MMM D, YYYY",
            },
        }

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = session.post(
                    search_url,
                    json=payload,
                    headers=search_headers,
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
            data = response.json()
        except ValueError as e:
            error_msg = f"Failed to parse JSON response: {e}"
            logger.error(f"{company['name']}: {error_msg}")
            return _error_result(company, error_msg, all_jobs)

        res_node = data.get("res", {})
        if total_available is None:
            total_available = res_node.get("totalRecords", 0)
            logger.info(f"{company['name']}: {total_available} total jobs found on Apple Careers")

        search_results = res_node.get("searchResults", [])
        if not search_results:
            break

        for raw in search_results:
            job = normalize_job(raw, company, filters, locale=locale)
            if posted_within_days is not None:
                if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                    continue
            all_jobs.append(job)
            if max_jobs and len(all_jobs) >= max_jobs:
                break

        if max_jobs and len(all_jobs) >= max_jobs:
            all_jobs = all_jobs[:max_jobs]
            break

        if total_available is not None and page * PAGE_SIZE >= total_available:
            break

        page += 1
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

