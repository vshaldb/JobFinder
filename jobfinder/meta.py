"""
Meta Careers Fetcher
Fetches job postings from Meta Careers (metacareers.com) using Relay GraphQL.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

META_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

DEFAULT_INDIA_OFFICES = [
    "Bangalore, India",
    "Gurgaon, India",
    "Hyderabad, India",
    "Mumbai, India",
    "New Delhi, India",
]

DOC_ID = "27129360303422352"
QUERY_NAME = "CareersJobSearchResultsV2DataQuery"


def fetch_job_date(job_id: str) -> Optional[str]:
    """Fetch detail page for a single Meta job and extract datePosted from LD+JSON."""
    try:
        url = f"https://www.metacareers.com/jobs/{job_id}/"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code == 200:
            blocks = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', resp.text)
            for block in blocks:
                try:
                    data = json.loads(block)
                    if isinstance(data, dict) and "datePosted" in data:
                        # Format is ISO string e.g. 2026-10-16T00:28:07-07:00
                        return str(data["datePosted"])[:10]
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Could not fetch date for Meta job {job_id}: {e}")
    return None


def normalize_job(raw: dict, company: dict, filters: dict, posted_on_date: Optional[str] = None) -> dict:
    """Normalize Meta job GraphQL item to standardized JobFinder schema."""
    job_id = str(raw.get("id", ""))
    title = raw.get("title", "Untitled Position")

    locations_list = raw.get("locations", [])
    location_str = ", ".join(locations_list) if locations_list else "Not specified"

    teams = raw.get("teams", [])
    sub_teams = raw.get("sub_teams", [])
    emp_parts = []
    if teams:
        emp_parts.extend(teams)
    if sub_teams:
        emp_parts.extend(sub_teams)
    emp_type = ", ".join(emp_parts)

    posted_on_str = posted_on_date or ""
    posted_days_ago = None
    if posted_on_str:
        try:
            job_dt = datetime.strptime(posted_on_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            posted_days_ago = max(0, (now_dt - job_dt).days)
        except Exception:
            pass

    remote_type = "Remote" if "remote" in location_str.lower() else "Onsite"
    job_url = f"https://www.metacareers.com/jobs/{job_id}/"

    return {
        "company": company["name"],
        "title": title,
        "job_id": job_id,
        "location": location_str,
        "employment_type": emp_type,
        "posted_on": posted_on_str,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/jobs/{job_id}/",
        "remote_type": remote_type,
        "source_ats": "meta",
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
    """Fetch jobs from Meta Careers using GraphQL."""
    landing_url = company.get("career_site_url", "https://www.metacareers.com/jobsearch/")
    logger.info(f"Fetching jobs from {company['name']} (Meta Careers) → {landing_url}")

    # 1. Warm up session & extract LSD token
    try:
        r_page = session.get(landing_url, headers=META_PAGE_HEADERS, timeout=20)
        r_page.raise_for_status()
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to access Meta Careers page: {e}"
        logger.error(f"{company['name']}: {error_msg}")
        return _error_result(company, error_msg, [])

    lsd_match = re.search(r'\["LSD",\[\],\{"token":"([^"]+)"\}', r_page.text)
    lsd = lsd_match.group(1) if lsd_match else ""

    # 2. Determine offices filter
    loc_filter = filters.get("location", "").strip().lower()
    if loc_filter:
        if loc_filter in ("india", "in", "ind"):
            offices = DEFAULT_INDIA_OFFICES
        else:
            # Custom location keyword
            offices = [o for o in DEFAULT_INDIA_OFFICES if loc_filter in o.lower()]
            if not offices:
                offices = [filters["location"].strip()]
    else:
        offices = company.get("offices", [])

    keyword = filters.get("keyword") or None

    graphql_payload = {
        "lsd": lsd,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": QUERY_NAME,
        "variables": json.dumps({
            "isLoggedIn": False,
            "search_input": {
                "q": keyword,
                "divisions": [],
                "offices": offices,
                "roles": [],
                "leadership_levels": [],
                "saved_jobs": [],
                "saved_searches": [],
                "sub_teams": [],
                "teams": [],
                "is_leadership": False,
                "is_remote_only": False,
                "sort_by_new": True,
                "results_per_page": None,
            },
            "viewasUserID": None,
        }),
        "server_timestamps": "true",
        "doc_id": DOC_ID,
    }

    graphql_headers = {
        "User-Agent": META_PAGE_HEADERS["User-Agent"],
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-FB-Friendly-Name": QUERY_NAME,
        "X-FB-LSD": lsd,
        "Origin": "https://www.metacareers.com",
        "Referer": landing_url,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    try:
        r_post = session.post(
            "https://www.metacareers.com/graphql",
            data=graphql_payload,
            headers=graphql_headers,
            timeout=25,
        )
        r_post.raise_for_status()
        resp_data = r_post.json()
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to execute Meta GraphQL query: {e}"
        logger.error(f"{company['name']}: {error_msg}")
        return _error_result(company, error_msg, [])
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse Meta GraphQL response: {e}"
        logger.error(f"{company['name']}: {error_msg}")
        return _error_result(company, error_msg, [])

    job_data_node = (
        resp_data.get("data", {})
        .get("job_search_with_featured_jobs_v2", {})
    )
    all_raw_jobs = job_data_node.get("all_jobs", [])
    total_available = len(all_raw_jobs)
    logger.info(f"{company['name']}: {total_available} total jobs found on Meta Careers")

    # Select candidates up to max_jobs
    candidate_jobs = all_raw_jobs
    if max_jobs and max_jobs > 0:
        candidate_jobs = candidate_jobs[:max_jobs]

    # Concurrently fetch posted date from detail pages (fast, threadpool capped at 5)
    dates_map: Dict[str, Optional[str]] = {}
    if candidate_jobs:
        job_ids_to_fetch = [j.get("id") for j in candidate_jobs if j.get("id")]
        with ThreadPoolExecutor(max_workers=min(5, len(job_ids_to_fetch))) as executor:
            future_to_id = {
                executor.submit(fetch_job_date, jid): jid
                for jid in job_ids_to_fetch
            }
            for future in as_completed(future_to_id):
                jid = future_to_id[future]
                try:
                    dates_map[jid] = future.result()
                except Exception:
                    dates_map[jid] = None

    all_jobs: List[dict] = []
    for raw in candidate_jobs:
        jid = str(raw.get("id", ""))
        posted_date = dates_map.get(jid)
        job = normalize_job(raw, company, filters, posted_on_date=posted_date)

        if posted_within_days is not None:
            if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                continue

        all_jobs.append(job)

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available,
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
