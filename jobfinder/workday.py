"""
Workday Careers Fetcher
Fetches job postings from Workday-based career portals using the CXS internal API.
"""

import re
import requests
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

WORKDAY_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

PAGE_LIMIT = 20          # Workday caps at 20 per page
REQUEST_DELAY = 1.0      # Seconds between paginated requests (be polite)
MAX_PAGES = 50           # Safety cap: never fetch more than 50 pages per company

# Synonyms for common location searches (e.g. India tech hubs)
LOCATION_SYNONYMS = {
    "india": [
        "india",
        "bengaluru",
        "bangalore",
        "noida",
        "hyderabad",
        "pune",
        "gurgaon",
        "gurugram",
        "chennai",
        "mumbai",
        "ahmedabad",
        "ind-",
        "ssir",
        "two horizon center",
    ],
    "bangalore": ["bangalore", "bengaluru", "ssir"],
    "bengaluru": ["bangalore", "bengaluru", "ssir"],
    "gurugram": ["gurugram", "gurgaon", "two horizon center"],
    "gurgaon": ["gurugram", "gurgaon", "two horizon center"],
    "pune": ["pune"],
    "hyderabad": ["hyderabad"],
}


def matches_location(job_location: str, target_location: str) -> bool:
    """Check if the job location matches the target location filter."""
    if not target_location:
        return True

    loc_clean = job_location.lower()
    target_clean = target_location.lower().strip()

    if target_clean in loc_clean:
        return True

    synonyms = LOCATION_SYNONYMS.get(target_clean, [])
    for syn in synonyms:
        if syn in loc_clean:
            return True

    return False

# ---------------------------------------------------------------------------
# Posted-date helpers
# ---------------------------------------------------------------------------

# Workday returns human-readable strings like:
#   "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago"
# We parse these into an approximate integer days-ago value for filtering.

_POSTED_PATTERNS = [
    (re.compile(r"today", re.I),             0),
    (re.compile(r"yesterday", re.I),         1),
    (re.compile(r"(\d+)\+?\s*day", re.I),    None),   # capture group 1 → days
    (re.compile(r"(\d+)\+?\s*week", re.I),   None),   # capture group 1 → weeks
    (re.compile(r"(\d+)\+?\s*month", re.I),  None),   # capture group 1 → months
]


def is_posted_date_str(val: str) -> bool:
    """Check if a string looks like a posted date (e.g. 'Posted 10 Days Ago', 'Yesterday')."""
    if not val:
        return False
    val_lower = val.lower().strip()
    if any(w in val_lower for w in ("posted", "yesterday", "today", "days ago", "day ago", "weeks ago", "week ago", "months ago", "month ago")):
        return True
    if re.search(r"\b\d+\+?\s*(day|week|month)s?\s*ago\b", val_lower):
        return True
    return False


def parse_posted_days_ago(posted_on: str) -> Optional[int]:
    """
    Convert a Workday postedOn or startDate string to approximate days-ago integer.
    Returns None if the string cannot be parsed.
    """
    if not posted_on:
        return None
    s = posted_on.strip()

    # Check ISO date format YYYY-MM-DD
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)
    except Exception:
        pass

    if re.search(r"today", s, re.I):
        return 0
    if re.search(r"yesterday", s, re.I):
        return 1

    m = re.search(r"(\d+)\+?\s*day", s, re.I)
    if m:
        return int(m.group(1))

    m = re.search(r"(\d+)\+?\s*week", s, re.I)
    if m:
        return int(m.group(1)) * 7

    m = re.search(r"(\d+)\+?\s*month", s, re.I)
    if m:
        return int(m.group(1)) * 30

    # "30+ Days Ago" → treat the number literally
    m = re.search(r"(\d+)", s)
    if m:
        return int(m.group(1))

    return None


def job_within_days(posted_on: str, max_days: int) -> bool:
    """
    Return True if the job was posted within *max_days* days.
    Jobs whose date cannot be parsed are kept (fail-open).
    """
    days_ago = parse_posted_days_ago(posted_on)
    if days_ago is None:
        return True          # unknown → include
    return days_ago <= max_days


def get_base_host(company: dict) -> str:
    """Return the base domain for a Workday tenant."""
    if company.get("host"):
        return company["host"]
    tenant = company["tenant"]
    datacenter = (company.get("datacenter") or "").strip()
    if datacenter:
        return f"{tenant}.{datacenter}.myworkdayjobs.com"
    return f"{tenant}.myworkdayjobs.com"


def build_api_url(company: dict) -> str:
    """Construct the Workday CXS API endpoint from a company config dict."""
    tenant = company["tenant"]
    site_name = company["site_name"]
    host = get_base_host(company)
    return f"https://{host}/wday/cxs/{tenant}/{site_name}/jobs"


def build_job_url(company: dict, external_path: str) -> str:
    """Build the full URL to a specific job posting."""
    site_name = company["site_name"]
    host = get_base_host(company)
    # external_path already starts with "/"
    return f"https://{host}/{site_name}{external_path}"


def build_request_body(company: dict, filters: dict, offset: int) -> dict:
    """Build the POST body for the Workday jobs API.

    Location strategy
    -----------------
    1. Companies with specific location bucket IDs (e.g. Broadcom, Samsung Semiconductor)
       do not support generic free-text country queries like "India". For these tenants,
       we pass their verified internal location IDs in ``appliedFacets["locations"]``.
    2. Standard tenants: we append the location string to ``searchText``, which works
       reliably across standard Workday instances.
    """
    applied_facets = {}
    search_parts = []

    if filters.get("keyword"):
        search_parts.append(filters["keyword"])

    location_filter = (filters.get("location") or "").strip()
    default_locations = company.get("default_locations", [])
    default_location_names = company.get("default_location_names", [])

    if location_filter:
        loc_lower = location_filter.lower()
        if default_locations:
            if loc_lower == "india":
                # Apply all default India location facet IDs
                applied_facets["locations"] = list(default_locations)
            else:
                # User requested a specific location (e.g. "Bangalore" or "Gurugram")
                matched_ids = []
                for loc_id, loc_name in zip(default_locations, default_location_names):
                    if loc_lower in loc_name.lower():
                        matched_ids.append(loc_id)
                if matched_ids:
                    applied_facets["locations"] = matched_ids
                else:
                    search_parts.append(location_filter)
        else:
            skip_country = (
                company.get("skip_country_filter", False)
                or company.get("skip_location_filter", False)
            )
            if not skip_country:
                search_parts.append(location_filter)

    if filters.get("job_family"):
        applied_facets["jobFamilyGroup"] = [filters["job_family"]]

    if filters.get("time_type"):
        applied_facets["timeType"] = [filters["time_type"]]

    return {
        "appliedFacets": applied_facets,
        "limit": PAGE_LIMIT,
        "offset": offset,
        "searchText": " ".join(search_parts),
    }


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize a raw Workday job posting dict into our unified schema."""
    external_path = raw.get("externalPath", "")
    job_url = build_job_url(company, external_path) if external_path else ""

    bullet_fields = raw.get("bulletFields", [])
    job_id = ""
    employment_type = ""
    posted_on = raw.get("postedOn", "")

    emp_keywords = {
        "full time", "full-time", "part time", "part-time",
        "regular", "contract", "intern", "internship",
        "temporary", "contingent", "fixed term", "fixed-term"
    }

    for field in bullet_fields:
        if not field:
            continue
        field_str = str(field).strip()

        # 1. Check if field contains posted date info (e.g. "Posted 10 Days Ago")
        if is_posted_date_str(field_str):
            if not posted_on:
                posted_on = field_str
            continue

        # 2. Check if known employment type
        if field_str.lower() in emp_keywords:
            employment_type = field_str
            continue

        # 3. Check if Job ID (numeric or alphanumeric like JR1234, R-101476, 21057, 2605212, 26-687)
        if any(ch.isdigit() for ch in field_str) and len(field_str) <= 30:
            job_id = field_str
        else:
            if not employment_type:
                employment_type = field_str

    # 4. Fallback for Job ID: check raw jobReqId
    if not job_id:
        job_id = raw.get("jobReqId", "")

    # 5. Fallback for Job ID: extract from externalPath suffix (e.g. ..._19905, ..._2605212, ..._26-687)
    if not job_id and external_path:
        m = re.search(r"_([A-Za-z0-9\-]+)(?:[?#]|$)", external_path)
        if m and any(ch.isdigit() for ch in m.group(1)):
            job_id = m.group(1)

    return {
        "company": company["name"],
        "title": raw.get("title", ""),
        "job_id": job_id,
        "location": raw.get("location", raw.get("locationsText", "")),
        "employment_type": employment_type,
        "posted_on": posted_on,
        "posted_days_ago": parse_posted_days_ago(posted_on),
        "url": job_url,
        "external_path": external_path,
        "remote_type": raw.get("remoteType", ""),
        "source_ats": "workday",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "_filters_applied": filters,
    }


def _enrich_missing_posted_dates(company: dict, jobs: List[dict], session: requests.Session) -> None:
    """Fetch job details concurrently to populate missing posted_on dates."""
    from concurrent.futures import ThreadPoolExecutor

    tenant = company["tenant"]
    site_name = company["site_name"]
    host = get_base_host(company)
    base_url = f"https://{host}/wday/cxs/{tenant}/{site_name}"

    def fetch_detail(job: dict) -> None:
        ext_path = job.get("external_path", "")
        if not ext_path:
            return
        url = f"{base_url}{ext_path}"
        try:
            resp = session.get(url, timeout=5)
            if resp.status_code == 200:
                info = resp.json().get("jobPostingInfo", {})
                posted_on = info.get("postedOn") or ""
                start_date = info.get("startDate") or ""
                # Prefer startDate if available as it provides exact ISO date
                final_posted = start_date if start_date else posted_on
                if final_posted:
                    job["posted_on"] = final_posted
                    job["posted_days_ago"] = parse_posted_days_ago(final_posted)
                if not job.get("job_id"):
                    job_req = info.get("jobReqId") or info.get("id") or ""
                    if job_req:
                        job["job_id"] = job_req
        except Exception as e:
            logger.debug(f"Failed to fetch detail for {ext_path}: {e}")

    with ThreadPoolExecutor(max_workers=min(len(jobs), 8)) as executor:
        list(executor.map(fetch_detail, jobs))


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Fetch all (or up to max_jobs) jobs for a single company.

    Args:
        company:             Company config dict.
        filters:             Filter dict forwarded to the API (keyword, location, etc.).
        session:             Shared requests.Session.
        max_jobs:            Cap on total jobs returned (None = unlimited).
        posted_within_days:  Only keep jobs posted within this many days.
                             Workday doesn't expose a server-side date facet, so
                             we parse the human-readable ``postedOn`` field and
                             filter client-side after fetching each page.

    Returns a result dict:
    {
        "company": str,
        "success": bool,
        "error": str | None,
        "total_available": int,
        "jobs_fetched": int,
        "jobs": list[dict],
    }
    """
    api_url = build_api_url(company)
    all_jobs = []
    offset = 0
    total_available = None
    page = 0

    logger.info(f"Fetching jobs from {company['name']} → {api_url}")

    # Construct headers with proper Origin/Referer
    tenant = company["tenant"]
    site_name = company["site_name"]
    host = get_base_host(company)
    base_url = f"https://{host}"

    headers = {
        **WORKDAY_HEADERS,
        "Origin": base_url,
        "Referer": f"{base_url}/{site_name}",
    }

    while True:
        if page >= MAX_PAGES:
            logger.warning(
                f"{company['name']}: Reached MAX_PAGES ({MAX_PAGES}). Stopping."
            )
            break

        body = build_request_body(company, filters, offset)

        try:
            response = session.post(
                api_url, json=body, headers=headers, timeout=30
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            error_msg = f"HTTP {status}: {e}"
            logger.error(f"{company['name']}: {error_msg}")
            return _error_result(company, error_msg, all_jobs)
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            logger.error(f"{company['name']}: {error_msg}")
            return _error_result(company, error_msg, all_jobs)

        try:
            data = response.json()
        except ValueError as e:
            error_msg = f"Failed to parse JSON: {e}"
            logger.error(f"{company['name']}: {error_msg}")
            return _error_result(company, error_msg, all_jobs)

        # On first page, record total
        if total_available is None:
            total_available = data.get("total", 0)
            logger.info(
                f"{company['name']}: {total_available} total jobs available"
            )

        postings = data.get("jobPostings", [])
        if not postings:
            break  # No more results

        page_jobs = [normalize_job(raw, company, filters) for raw in postings]

        # ── Client-side filters (location + posted-date) ────────────────
        location_filter = (filters.get("location") or "").strip()
        filtered_page = []
        for job in page_jobs:
            if location_filter and not matches_location(job["location"], location_filter):
                continue
            if posted_within_days is not None and not job_within_days(job["posted_on"], posted_within_days):
                continue
            filtered_page.append(job)

        all_jobs.extend(filtered_page)

        offset += len(postings)
        page += 1

        logger.info(
            f"{company['name']}: Fetched page {page} "
            f"({len(all_jobs)}/{total_available or '?'})"
        )

        # Honour max_jobs cap
        if max_jobs and len(all_jobs) >= max_jobs:
            all_jobs = all_jobs[:max_jobs]
            break

        # All jobs fetched
        if total_available is not None and offset >= total_available:
            break

        # Polite delay between pages
        if page > 1:
            time.sleep(REQUEST_DELAY)

    # For any returned jobs where posted_on is still empty, enrich via detail API
    missing_date_jobs = [j for j in all_jobs if not j.get("posted_on") and j.get("external_path")]
    if missing_date_jobs:
        _enrich_missing_posted_dates(company, missing_date_jobs, session)

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
