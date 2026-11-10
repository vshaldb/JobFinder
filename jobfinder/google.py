"""
Google Careers Fetcher
Fetches job postings from Google Careers (about.google/careers) portal.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

GOOGLE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PAGE_SIZE = 20
REQUEST_DELAY = 0.5
MAX_PAGES = 50


def normalize_job(raw: list, company: dict, filters: dict) -> dict:
    """Normalize Google raw array item to standardized JobFinder schema."""
    job_id = str(raw[0]) if len(raw) > 0 and raw[0] is not None else ""
    title = str(raw[1]) if len(raw) > 1 and raw[1] is not None else "Untitled Position"

    # Locations in index 9
    locations: List[str] = []
    if len(raw) > 9 and isinstance(raw[9], list):
        for loc_entry in raw[9]:
            if isinstance(loc_entry, list) and loc_entry:
                loc_name = loc_entry[0]
                if loc_name:
                    locations.append(str(loc_name))
            elif isinstance(loc_entry, str):
                locations.append(loc_entry)
    location_str = ", ".join(locations) if locations else "Not specified"

    # Employment type in index 8 or 20
    emp_type = ""
    if len(raw) > 8 and isinstance(raw[8], list):
        emp_type = ", ".join(str(x) for x in raw[8])
    elif len(raw) > 8 and isinstance(raw[8], str) and raw[8] not in ("en-US", "en"):
        emp_type = raw[8]

    # Timestamp in index 12 or 13
    posted_on_str = ""
    posted_days_ago = None
    posted_ts = None
    if len(raw) > 12 and isinstance(raw[12], list) and raw[12]:
        posted_ts = raw[12][0]
    elif len(raw) > 13 and isinstance(raw[13], list) and raw[13]:
        posted_ts = raw[13][0]

    if posted_ts and isinstance(posted_ts, (int, float)):
        try:
            job_dt = datetime.fromtimestamp(posted_ts, tz=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            posted_days_ago = max(0, (now_dt - job_dt).days)
            posted_on_str = job_dt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"Could not parse Google timestamp {posted_ts}: {e}")

    job_url = f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"

    return {
        "company": company["name"],
        "title": title,
        "job_id": job_id,
        "location": location_str,
        "employment_type": emp_type,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/about/careers/applications/jobs/results/{job_id}",
        "remote_type": "Onsite",
        "source_ats": "google",
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
    """Fetch jobs from Google Careers."""
    base_url = company.get(
        "career_site_url",
        "https://www.google.com/about/careers/applications/jobs/results",
    )
    all_jobs: List[dict] = []
    total_available = None
    page = 1

    location = filters.get("location", "")
    keyword = filters.get("keyword", "")

    logger.info(f"Fetching jobs from {company['name']} (Google Careers) → {base_url}")

    while True:
        if page > MAX_PAGES:
            logger.warning(f"{company['name']}: Reached MAX_PAGES ({MAX_PAGES}). Stopping.")
            break

        params = {"page": page}
        if location:
            params["location"] = location
        if keyword:
            params["q"] = keyword

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = session.get(
                    base_url,
                    params=params,
                    headers=GOOGLE_HEADERS,
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

        # Extract AF_initDataCallback with ds:1
        html = response.text
        marker = "AF_initDataCallback({key: 'ds:1'"
        idx = html.find(marker)
        if idx == -1:
            logger.warning(f"{company['name']}: AF_initDataCallback marker not found on page {page}.")
            break

        data_idx = html.find("data:", idx)
        if data_idx == -1:
            logger.warning(f"{company['name']}: 'data:' field not found in callback on page {page}.")
            break

        payload_str = html[data_idx + 5:].lstrip()
        try:
            parsed_data, _ = json.JSONDecoder().raw_decode(payload_str)
        except json.JSONDecodeError as e:
            error_msg = f"Failed to decode Google payload JSON: {e}"
            logger.error(f"{company['name']}: {error_msg}")
            return _error_result(company, error_msg, all_jobs)

        if not isinstance(parsed_data, list) or len(parsed_data) == 0:
            break

        jobs_list = parsed_data[0] if isinstance(parsed_data[0], list) else []
        if total_available is None and len(parsed_data) > 2 and isinstance(parsed_data[2], int):
            total_available = parsed_data[2]
            logger.info(f"{company['name']}: {total_available} total jobs found on Google Careers")

        if not jobs_list:
            break

        for raw in jobs_list:
            if not isinstance(raw, list):
                continue
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

