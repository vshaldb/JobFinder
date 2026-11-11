"""
SAP SuccessFactors (RMK) Careers Fetcher
Fetches job postings from SAP SuccessFactors Recruiting Marketing portals
(e.g. Skyworks Solutions at https://careers.skyworksinc.com).
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

SF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_PAGES = 100


def parse_sf_date(date_str: str) -> Tuple[str, Optional[int]]:
    """Parse SuccessFactors RMK date string (e.g. '7/14/26' or '2026-10-08') cleanly."""
    if not date_str:
        return "", None
    clean = str(date_str).strip()
    now = datetime.now(timezone.utc)

    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
            days_ago = max(0, (now - dt).days)
            return dt.strftime("%Y-%m-%d"), days_ago
        except ValueError:
            continue

    return clean, None


def map_search_location(location_filter: str) -> str:
    """Map common India city aliases so RMK location lookup finds Bangalore/Gurgaon cleanly."""
    loc = (location_filter or "").strip()
    loc_lower = loc.lower()
    if loc_lower == "bengaluru":
        return "Bangalore"
    if loc_lower == "gurugram":
        return "Gurgaon"
    return loc


def matches_keyword(title: str, keyword: str) -> bool:
    """Client-side keyword fallback filter."""
    if not keyword:
        return True
    title_lower = title.lower()
    kw_lower = keyword.lower().strip()
    if kw_lower in title_lower:
        return True
    return any(w in title_lower for w in kw_lower.split())


def normalize_job(raw_item: dict, company: dict, base_url: str, locale: str, filters: dict) -> dict:
    """Normalize SuccessFactors RMK job entry into standardized schema."""
    resp = raw_item.get("response", raw_item) if isinstance(raw_item, dict) else {}

    job_id = str(resp.get("id") or "").strip()
    title = str(resp.get("unifiedStandardTitle") or resp.get("title") or "").strip()
    url_title = str(resp.get("urlTitle") or resp.get("unifiedUrlTitle") or "").strip()
    if not url_title:
        url_title = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-") or "job"

    locs = [str(x).strip() for x in (resp.get("jobLocationShort") or []) if str(x).strip()]
    location_str = "; ".join(dict.fromkeys(locs))

    posted_on, posted_days_ago = parse_sf_date(resp.get("unifiedStandardStart") or "")

    funcs = [str(x).strip() for x in (resp.get("jobFunction_obj") or []) if str(x).strip()]
    emp_type = ", ".join(dict.fromkeys(funcs))

    job_url = f"{base_url}/job/{url_title}/{job_id}-{locale}" if job_id else f"{base_url}/search/"

    return {
        "company": company["name"],
        "title": title,
        "job_id": job_id,
        "location": location_str,
        "employment_type": emp_type,
        "posted_on": posted_on,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/job/{url_title}/{job_id}-{locale}" if job_id else "",
        "remote_type": "",
        "source_ats": "successfactors",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_filters_applied": filters,
    }


def _get_csrf_token(session: requests.Session, base_url: str) -> str:
    """Pre-warm search page session to obtain cookies and CSRFToken."""
    search_page = f"{base_url}/search/?q=&locationsearch="
    resp = session.get(
        search_page,
        headers={
            "User-Agent": SF_HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=25,
    )
    resp.raise_for_status()
    m = re.search(r"CSRFToken[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", resp.text)
    return m.group(1) if m else ""


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """Fetch matching jobs from a SAP SuccessFactors RMK career portal."""
    base_url = company["career_site_url"].rstrip("/")
    locale = company.get("locale", "en_US")
    api_url = f"{base_url}/services/recruiting/v1/jobs"

    keyword_filter = (filters.get("keyword") or "").strip()
    location_filter = map_search_location(filters.get("location") or "")

    logger.info(f"Fetching jobs from {company['name']} (SAP SuccessFactors: {base_url})")

    try:
        csrf_token = _get_csrf_token(session, base_url)
    except requests.exceptions.RequestException as e:
        err = f"Failed to initialize SuccessFactors session: {e}"
        logger.error(f"{company['name']}: {err}")
        return {
            "company": company["name"],
            "success": False,
            "error": err,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    post_headers = dict(SF_HEADERS)
    post_headers.update({
        "Content-Type": "application/json",
        "Referer": f"{base_url}/search/",
        "Origin": base_url,
    })
    if csrf_token:
        post_headers["X-CSRF-Token"] = csrf_token

    matched_jobs: List[dict] = []
    seen_ids = set()
    total_available = 0

    for page in range(MAX_PAGES):
        payload = {
            "keywords": keyword_filter,
            "locale": locale,
            "location": location_filter,
            "pageNumber": page,
            "sortBy": "recent",
        }
        try:
            resp = session.post(api_url, json=payload, headers=post_headers, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            err = f"API request failed on page {page}: {e}"
            logger.error(f"{company['name']}: {err}")
            if not matched_jobs:
                return {
                    "company": company["name"],
                    "success": False,
                    "error": err,
                    "total_available": 0,
                    "jobs_fetched": 0,
                    "jobs": [],
                }
            break
        except ValueError as e:
            err = f"Invalid JSON response on page {page}: {e}"
            logger.error(f"{company['name']}: {err}")
            break

        if page == 0:
            total_available = int(data.get("totalJobs") or 0)

        raw_list = data.get("jobSearchResult") or []
        if not raw_list:
            break

        for raw_item in raw_list:
            job = normalize_job(raw_item, company, base_url, locale, filters)
            if not job["title"] or not job["job_id"]:
                continue
            if job["job_id"] in seen_ids:
                continue
            seen_ids.add(job["job_id"])

            if not matches_keyword(job["title"], keyword_filter):
                continue

            if posted_within_days is not None and posted_within_days > 0:
                if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                    continue

            matched_jobs.append(job)
            if max_jobs and len(matched_jobs) >= max_jobs:
                break

        if max_jobs and len(matched_jobs) >= max_jobs:
            break

        if (page + 1) * 10 >= total_available and total_available > 0:
            break

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available,
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }

