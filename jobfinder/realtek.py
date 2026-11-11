"""
Realtek Semiconductor Careers Fetcher
Fetches job postings from Realtek's recruitment portal.
Endpoint: https://recruit.realtek.com/Job/GetAllJobList
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

REALTEK_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

LOCATION_LABELS = {
    "新竹科學園區": "Hsinchu Science Park, Taiwan",
    "台北市中山區": "Taipei, Taiwan",
    "台南科學園區": "Tainan Science Park, Taiwan",
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
    ],
    "bangalore": ["bangalore", "bengaluru"],
    "bengaluru": ["bangalore", "bengaluru"],
    "taiwan": ["taiwan", "hsinchu", "taipei", "tainan", "新竹", "台北", "台南"],
}


def parse_realtek_date(date_str: Optional[str]) -> Tuple[str, Optional[int]]:
    """Parse optional ModDate string from Realtek API."""
    if not date_str:
        return "", None
    clean = str(date_str).strip()[:10]
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
        return clean, days_ago
    except Exception:
        return clean, None


def matches_location(title: str, raw_loc: str, mapped_loc: str, target_location: str) -> bool:
    """Check job location and title tags (Realtek tags regional roles like '(India) BT/BLE FAE' in title)."""
    if not target_location:
        return True
    target_clean = target_location.lower().strip()
    synonyms = LOCATION_SYNONYMS.get(target_clean, [target_clean])
    haystack = f"{raw_loc} {mapped_loc} {title}".lower()
    return target_clean in haystack or any(syn in haystack for syn in synonyms)


def matches_keyword(title: str, keyword: str) -> bool:
    """Client-side keyword filter."""
    if not keyword:
        return True
    title_lower = title.lower()
    kw_lower = keyword.lower().strip()
    if kw_lower in title_lower:
        return True
    return any(w in title_lower for w in kw_lower.split())


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize Realtek JSON job entry into standardized JobFinder schema."""
    opp_id = str(raw.get("JobOppId") or raw.get("JobId") or "").strip()
    title = str(raw.get("JobTitle") or "").strip()
    raw_loc = str(raw.get("Location") or "").strip()
    mapped_loc = LOCATION_LABELS.get(raw_loc, raw_loc)

    # Realtek lists India field roles in title under Hsinchu HQ
    if "(india)" in title.lower() or "india" in title.lower():
        display_loc = f"India ({mapped_loc})" if mapped_loc else "India"
    else:
        display_loc = mapped_loc

    posted_on, posted_days_ago = parse_realtek_date(raw.get("ModDate"))
    job_url = f"https://recruit.realtek.com/Job/JobDetail?jobid={opp_id}&lang=en-GB"

    return {
        "company": company["name"],
        "title": title,
        "job_id": opp_id,
        "location": display_loc,
        "employment_type": str(raw.get("JobType") or "").strip(),
        "posted_on": posted_on,
        "posted_days_ago": posted_days_ago,
        "url": job_url,
        "external_path": f"/Job/JobDetail?jobid={opp_id}&lang=en-GB",
        "remote_type": "",
        "source_ats": "realtek",
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
    """Fetch jobs from Realtek's recruitment API."""
    api_url = "https://recruit.realtek.com/Job/GetAllJobList"
    keyword_filter = (filters.get("keyword") or "").strip()
    location_filter = (filters.get("location") or "").strip()

    logger.info(f"Fetching jobs from {company['name']} (Realtek portal)")

    try:
        resp = session.get(api_url, headers=REALTEK_HEADERS, timeout=25)
        resp.raise_for_status()
        payload = resp.json()
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
    except ValueError as e:
        err = f"Invalid JSON response: {e}"
        logger.error(f"{company['name']}: {err}")
        return {
            "company": company["name"],
            "success": False,
            "error": err,
            "total_available": 0,
            "jobs_fetched": 0,
            "jobs": [],
        }

    raw_jobs = payload.get("Data") or []
    matched_jobs: List[dict] = []
    seen_ids = set()

    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("JobTitle") or "").strip()
        raw_loc = str(raw.get("Location") or "").strip()
        mapped_loc = LOCATION_LABELS.get(raw_loc, raw_loc)

        if not title:
            continue
        if not matches_keyword(title, keyword_filter):
            continue
        if not matches_location(title, raw_loc, mapped_loc, location_filter):
            continue

        job = normalize_job(raw, company, filters)
        jid = job["job_id"]
        if not jid or jid in seen_ids:
            continue
        seen_ids.add(jid)

        if posted_within_days is not None and posted_within_days > 0:
            if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                continue

        matched_jobs.append(job)

    total_available = len(matched_jobs) if (location_filter or keyword_filter) else len(raw_jobs)
    if max_jobs and len(matched_jobs) > max_jobs:
        matched_jobs = matched_jobs[:max_jobs]

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available,
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }
