"""
Amazon Jobs Fetcher
Fetches job postings from Amazon Jobs (amazon.jobs) public JSON API.
Defaulted to "Software Development" category to filter for tech roles.
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

AMAZON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

PAGE_LIMIT = 10
REQUEST_DELAY = 0.5
MAX_PAGES = 50


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize Amazon job JSON item to standardized JobFinder schema."""
    job_id = str(raw.get("id_icims") or raw.get("id", ""))
    title = raw.get("title", "Untitled Position")

    location_str = (
        raw.get("normalized_location")
        or raw.get("city")
        or raw.get("location")
        or "Not specified"
    )

    posted_date_raw = raw.get("posted_date", "")
    posted_on_str = ""
    posted_days_ago = None

    if posted_date_raw:
        try:
            clean_date = re.sub(r"\s+", " ", posted_date_raw.strip())
            job_dt = datetime.strptime(clean_date, "%B %d, %Y").replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            posted_days_ago = max(0, (now_dt - job_dt).days)
            posted_on_str = job_dt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"Could not parse Amazon posted_date '{posted_date_raw}': {e}")

    job_path = raw.get("job_path", "")
    job_url = f"https://www.amazon.jobs{job_path}" if job_path else raw.get("url_next_step", "")

    emp_type = raw.get("job_schedule_type") or raw.get("job_category", "")
    remote_type = "Remote" if "remote" in location_str.lower() else "Onsite"

    return {
        "company": company["name"],
        "title": title,
        "job_id": job_id,
        "location": location_str,
        "employment_type": emp_type,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": job_path,
        "remote_type": remote_type,
        "source_ats": "amazon",
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
    """Fetch jobs from Amazon Jobs API."""
    search_api = company.get("api_url", "https://www.amazon.jobs/en/search.json")
    category = company.get("category", "software-development")
    sort = company.get("sort", "recent")

    logger.info(f"Fetching jobs from {company['name']} (Amazon Jobs) [category: {category}]")

    all_jobs: List[dict] = []
    offset = 0
    total_available = None
    page = 0

    loc_filter = filters.get("location", "").strip().lower()
    keyword = filters.get("keyword", "")

    country_param = None
    city_param = None
    if loc_filter:
        if loc_filter in ("india", "in", "ind"):
            country_param = "IND"
        else:
            # Check if city or country
            city_param = filters["location"].strip()
            country_param = company.get("country", "IND")
    else:
        country_param = company.get("country")

    while True:
        if page >= MAX_PAGES:
            logger.warning(f"{company['name']}: Reached MAX_PAGES ({MAX_PAGES}). Stopping.")
            break

        params = {
            "category[]": category,
            "sort": sort,
            "result_limit": PAGE_LIMIT,
            "offset": offset,
        }
        if country_param:
            params["country"] = country_param
        if city_param:
            params["city"] = city_param
        if keyword:
            params["base_query"] = keyword

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = session.get(
                    search_api,
                    params=params,
                    headers=AMAZON_HEADERS,
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

        if total_available is None:
            total_available = data.get("hits", 0)
            logger.info(f"{company['name']}: {total_available} total jobs found on Amazon Jobs")

        jobs_list = data.get("jobs", [])
        if not jobs_list:
            break

        for raw in jobs_list:
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

        offset += len(jobs_list)
        page += 1

        if total_available is not None and offset >= total_available:
            break

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

