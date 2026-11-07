"""
iCIMS Careers Fetcher
Fetches job postings from iCIMS-powered career portals, including custom
branded / TalentBrew portals (like ARM Experienced Professionals portal)
and standard iCIMS portals (*.icims.com).
"""

import html
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import requests

logger = logging.getLogger(__name__)

ICIMS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# Synonyms for location searches (consistent with other ATS modules)
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
    ],
    "bangalore": ["bangalore", "bengaluru"],
    "bengaluru": ["bangalore", "bengaluru"],
    "noida": ["noida", "delhi", "gurgaon", "gurugram", "ncr"],
}


def matches_location(job_location: str, target_location: str) -> bool:
    """Check if the job location matches the target location filter."""
    if not target_location:
        return True

    loc_clean = job_location.lower()
    target_clean = target_location.lower().strip()

    # Direct substring check
    if target_clean in loc_clean:
        return True

    # Synonym check
    synonyms = LOCATION_SYNONYMS.get(target_clean, [])
    for syn in synonyms:
        if syn in loc_clean:
            return True

    return False


def matches_keyword(job_title: str, target_keyword: str) -> bool:
    """Check if the job title matches the keyword query."""
    if not target_keyword:
        return True
    title_lower = job_title.lower()
    target_lower = target_keyword.lower().strip()
    if target_lower in title_lower:
        return True
    words = target_lower.split()
    return any(w in title_lower for w in words)


def parse_iso_date(date_str: str) -> Tuple[str, Optional[int]]:
    """Parse ISO date string into (YYYY-MM-DD, days_ago)."""
    if not date_str:
        return "", None
    try:
        # Handle fractional seconds and timezone markers for Python 3.9 compatibility
        clean = re.sub(r"(\.\d{6})\d+", r"\1", date_str)
        if re.search(r"[+-]\d{4}$", clean):
            clean = clean[:-2] + ":" + clean[-2:]
        elif clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = max(0, (now - dt).days)
        return dt.strftime("%Y-%m-%d"), days_ago
    except Exception as e:
        logger.debug(f"Could not parse date '{date_str}': {e}")
        return date_str[:10], None


def fetch_job_detail_info(session: requests.Session, job_url: str) -> Tuple[str, Optional[int], Optional[str]]:
    """
    Fetch job detail page to extract exact Schema.org JobPosting datePosted and actual Job/Req ID.
    TalentBrew / ARM job pages contain:
    - datePosted in JSON-LD
    - "name":"Job ID","value":"2026-19327" or data-gtm-prop="ReqID" content="2026-19327"
    """
    try:
        resp = session.get(job_url, headers=ICIMS_HEADERS, timeout=8)
        if resp.status_code == 200:
            text = resp.text
            date_str = ""
            days_ago = None
            m_date = re.search(r'\"datePosted\"\s*:\s*\"([^\"]+)\"', text)
            if m_date:
                date_str, days_ago = parse_iso_date(m_date.group(1).strip())

            # Extract actual Job / Requisition ID
            req_id = None
            m_req = re.search(r'[\"\']name[\"\']\s*:\s*[\"\']Job ID[\"\']\s*,\s*[\"\']value[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', text, re.I)
            if m_req:
                req_id = m_req.group(1).strip()
            if not req_id:
                m_req2 = re.search(r'data-gtm-prop=[\"\']ReqID[\"\'][^>]*content=[\"\']([^\"\']+)[\"\']|content=[\"\']([^\"\']+)[\"\'][^>]*data-gtm-prop=[\"\']ReqID[\"\']', text, re.I)
                if m_req2:
                    req_id = (m_req2.group(1) or m_req2.group(2)).strip()
            if not req_id:
                m_req3 = re.search(r'name=[\"\'](?:reqid|job-ats-req-id)[\"\'][^>]*content=[\"\']([^\"\']+)[\"\']', text, re.I)
                if m_req3:
                    req_id = m_req3.group(1).strip()

            return date_str, days_ago, req_id
    except Exception as e:
        logger.debug(f"Could not fetch details from {job_url}: {e}")
    return "", None, None


def fetch_talentbrew_icims_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Fetch jobs from TalentBrew / custom iCIMS portal (e.g. ARM Experienced Portal).
    Uses the AJAX search endpoint: https://careers.arm.com/search-jobs/results
    """
    base_url = company.get("career_site_url", "https://careers.arm.com").rstrip("/")
    ajax_url = company.get("ajax_search_url") or f"{base_url}/search-jobs/results"

    portal_type = company.get("portal_type", "experienced").lower()
    keyword_filter = filters.get("keyword", "")
    location_filter = filters.get("location", "")

    page = 1
    records_per_page = 100
    matched_jobs: List[dict] = []
    total_available = 0
    max_pages = 50

    # Pass keyword or location to search endpoint to prioritize matching jobs
    search_kw = keyword_filter or location_filter

    while page <= max_pages:
        params: Dict[str, str] = {
            "CurrentPage": str(page),
            "RecordsPerPage": str(records_per_page),
            "Keywords": search_kw,
            "SearchResultsModuleName": "Search Results",
            "SearchType": "5",
            "SortCriteria": "0",
            "SortDirection": "1",
        }

        # Filter for Experienced Professional if portal_type is experienced
        if portal_type == "experienced":
            params.update({
                "CustomFacetName": "custom_fields.ExperienceLevel",
                "FacetTerm": "Experienced Professional",
                "FacetType": "5",
            })

        logger.debug(f"Fetching {company['name']} jobs page {page} from {ajax_url}")

        try:
            resp = session.get(ajax_url, params=params, headers=ICIMS_HEADERS, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            err = f"Request error on page {page}: {e}"
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
            err = f"Failed to parse JSON response on page {page}: {e}"
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

        results_html = data.get("results", "")
        if not results_html:
            break

        cards = re.findall(r"<li[^>]*>(.*?)</li>", results_html, re.S)
        if not cards:
            break

        total_available += len(cards)

        for card in cards:
            # Extract link, job-id, and title
            m = re.search(
                r'class=[\"\']job-card__title[^\"]*[\"\'][^>]*href=[\"\']([^\"\']*)[\"\'][^>]*data-job-id=[\"\']([^\"\']*)[\"\'][^>]*>(.*?)</a>',
                card,
                re.S,
            )
            if not m:
                m = re.search(
                    r'class=[\"\']job-card__title[^\"]*[\"\'][^>]*data-job-id=[\"\']([^\"\']*)[\"\'][^>]*href=[\"\']([^\"\']*)[\"\'][^>]*>(.*?)</a>',
                    card,
                    re.S,
                )

            if not m:
                continue

            if "data-job-id" in m.group(0).split("href")[0]:
                job_id, href, title_raw = m.group(1), m.group(2), m.group(3)
            else:
                href, job_id, title_raw = m.group(1), m.group(2), m.group(3)

            title = html.unescape(title_raw).strip()

            loc_m = re.search(r'class=[\"\']location[\"\'][^>]*>(.*?)</span>', card, re.S)
            location = html.unescape(loc_m.group(1)).strip() if loc_m else ""

            cat_m = re.search(r'class=[\"\']category[\"\'][^>]*>(.*?)</span>', card, re.S)
            category = html.unescape(cat_m.group(1)).strip() if cat_m else ""

            full_job_url = f"{base_url}{href}" if href.startswith("/") else href

            # Keyword filter (fallback client-side verification)
            if not matches_keyword(title, keyword_filter):
                continue

            # Location filter
            if not matches_location(location, location_filter):
                continue

            remote_type = ""
            loc_lower = location.lower()
            if "remote" in loc_lower:
                remote_type = "Remote"
            elif "hybrid" in loc_lower:
                remote_type = "Hybrid"

            job_entry = {
                "company": company["name"],
                "title": title,
                "job_id": job_id,
                "location": location,
                "employment_type": category or "Experienced Professional",
                "posted_on": "",
                "posted_days_ago": None,
                "url": full_job_url,
                "external_path": href,
                "remote_type": remote_type,
                "source_ats": "icims",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "_filters_applied": filters,
            }
            matched_jobs.append(job_entry)

            # Check if we have enough candidates before fetching dates
            target_count = (max_jobs * 2) if (max_jobs and posted_within_days) else max_jobs
            if target_count and len(matched_jobs) >= target_count:
                break

        target_count = (max_jobs * 2) if (max_jobs and posted_within_days) else max_jobs
        if target_count and len(matched_jobs) >= target_count:
            break

        # If page had fewer cards than records_per_page, we've reached the end
        if len(cards) < records_per_page:
            break

        page += 1

    # Fetch accurate posted dates and actual Job IDs from job detail pages concurrently
    if matched_jobs:
        from concurrent.futures import ThreadPoolExecutor

        def _resolve_details(job: dict) -> None:
            url = job.get("url")
            if url:
                p_date, p_days, req_id = fetch_job_detail_info(session, url)
                if p_date:
                    job["posted_on"] = p_date
                    job["posted_days_ago"] = p_days
                if req_id:
                    job["job_id"] = req_id

        workers = min(10, len(matched_jobs))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(_resolve_details, matched_jobs))

        if posted_within_days is not None:
            matched_jobs = [
                j for j in matched_jobs
                if j.get("posted_days_ago") is None or j["posted_days_ago"] <= posted_within_days
            ]

        if max_jobs:
            matched_jobs = matched_jobs[:max_jobs]

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available if total_available > 0 else len(matched_jobs),
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }


def fetch_standard_icims_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Fetch jobs from standard iCIMS portal: https://{subdomain}.icims.com/jobs/search?in_iframe=1
    """
    subdomain = company.get("subdomain") or company.get("tenant")
    portal_host = f"https://{subdomain}.icims.com" if "://" not in subdomain else subdomain.rstrip("/")
    search_endpoint = f"{portal_host}/jobs/search"

    keyword_filter = filters.get("keyword", "")
    location_filter = filters.get("location", "")

    page = 0
    matched_jobs: List[dict] = []
    total_available = 0
    max_pages = 25

    while page < max_pages:
        params = {
            "in_iframe": "1",
            "pr": str(page),
            "searchKeyword": keyword_filter,
            "searchLocation": location_filter,
        }

        try:
            resp = session.get(search_endpoint, params=params, headers=ICIMS_HEADERS, timeout=25)
            resp.raise_for_status()
            html_content = resp.text
        except requests.exceptions.RequestException as e:
            err = f"Request error on page {page}: {e}"
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

        # Search for job links e.g. href="/jobs/1234/software-engineer/job"
        job_links = re.findall(
            r'<a[^>]*class=[\"\'][^\"\']*iCIMS_Anchor[^\"]*[\"\'][^>]*href=[\"\']([^\"\']*/jobs/(\d+)/[^\"\']*)[\"\'][^>]*>(.*?)</a>',
            html_content,
            re.S | re.I,
        )
        if not job_links:
            # Fallback regex for standard link pattern
            job_links = re.findall(
                r'<a[^>]*href=[\"\']([^\"\']*/jobs/(\d+)/[^\"\']*)[\"\'][^>]*>(.*?)</a>',
                html_content,
                re.S | re.I,
            )

        if not job_links:
            break

        total_available += len(job_links)

        for href, job_id, title_raw in job_links:
            title = re.sub(r"<[^>]+>", "", title_raw)
            title = html.unescape(title).strip()
            if not title or title.lower() in ("apply", "apply now", "view job"):
                continue

            full_job_url = f"{portal_host}{href}" if href.startswith("/") else href

            # Keyword filter
            if not matches_keyword(title, keyword_filter):
                continue

            job_entry = {
                "company": company["name"],
                "title": title,
                "job_id": job_id,
                "location": location_filter or "Multiple Locations",
                "employment_type": "Full-Time",
                "posted_on": "",
                "posted_days_ago": None,
                "url": full_job_url,
                "external_path": href,
                "remote_type": "",
                "source_ats": "icims",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "_filters_applied": filters,
            }
            matched_jobs.append(job_entry)

            if max_jobs and len(matched_jobs) >= max_jobs:
                break

        if max_jobs and len(matched_jobs) >= max_jobs:
            break

        page += 1

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available if total_available > 0 else len(matched_jobs),
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }


def fetch_jibe_icims_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Fetch jobs from Jibe / iCIMS Candidate Experience API (e.g. AMD at https://careers.amd.com/api/jobs).
    """
    api_url = company.get("api_url") or "https://careers.amd.com/api/jobs"
    base_site_url = company.get("career_site_url", "https://careers.amd.com").rstrip("/")

    keyword_filter = filters.get("keyword", "")
    location_filter = filters.get("location", "")

    page = 1
    limit = 100
    matched_jobs: List[dict] = []
    total_available = 0
    max_pages = 50

    while page <= max_pages:
        params: Dict[str, str] = {
            "page": str(page),
            "limit": str(limit),
        }
        if keyword_filter:
            params["keywords"] = keyword_filter
        if location_filter:
            params["country"] = location_filter

        logger.debug(f"Fetching {company['name']} jobs page {page} from {api_url}")

        try:
            resp = session.get(api_url, params=params, headers=ICIMS_HEADERS, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            err = f"Request error on page {page}: {e}"
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
            err = f"Failed to parse JSON response on page {page}: {e}"
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

        raw_jobs = data.get("jobs", [])
        if page == 1:
            total_available = data.get("totalCount") or data.get("count") or len(raw_jobs)

        if not raw_jobs:
            break

        for item in raw_jobs:
            job_data = item.get("data", item) if isinstance(item, dict) else {}
            title = job_data.get("title", "").strip()
            if not title:
                continue

            city = job_data.get("city") or ""
            country = job_data.get("country") or ""
            full_loc = job_data.get("full_location") or (f"{city}, {country}".strip(", ") if (city or country) else "")

            # Keyword filter (fallback client-side check)
            if not matches_keyword(title, keyword_filter):
                continue

            # Location filter check
            if not matches_location(full_loc, location_filter):
                continue

            date_val = job_data.get("posted_date") or job_data.get("create_date") or job_data.get("update_date") or ""
            posted_on_str, posted_days_ago = parse_iso_date(date_val)

            # Date filter
            if posted_within_days is not None:
                if posted_days_ago is not None and posted_days_ago > posted_within_days:
                    continue

            slug = str(job_data.get("slug") or job_data.get("req_id") or "")
            job_id = str(job_data.get("req_id") or slug or "")

            # Direct job opening URL on the company candidate portal:
            # Note: The API's apply_url (e.g. *.icims.com/jobs/.../login) requires candidate login
            # and bounces unauthenticated users back to the generic careers homepage.
            # The public job page displaying full description and apply button is at /careers-home/jobs/{slug}
            # (or /jobs/{slug} for sub-paths like /external).
            if slug:
                if base_site_url.endswith("/external"):
                    job_url = f"{base_site_url}/jobs/{slug}"
                else:
                    job_url = f"{base_site_url}/careers-home/jobs/{slug}"
            else:
                job_url = job_data.get("apply_url") or base_site_url

            external_path = f"/jobs/{slug}" if slug else ""

            # Category / employment type
            emp_type = job_data.get("employment_type") or ""
            categories = job_data.get("categories") or []
            cat_names = [c.get("name") for c in categories if isinstance(c, dict) and c.get("name")]
            dept_or_type = emp_type or (", ".join(cat_names) if cat_names else "")

            remote_type = ""
            loc_lower = full_loc.lower()
            if "remote" in loc_lower:
                remote_type = "Remote"
            elif "hybrid" in loc_lower:
                remote_type = "Hybrid"

            job_entry = {
                "company": company["name"],
                "title": title,
                "job_id": job_id,
                "location": full_loc,
                "employment_type": dept_or_type,
                "posted_on": posted_on_str,
                "posted_days_ago": posted_days_ago,
                "url": job_url,
                "external_path": external_path,
                "remote_type": remote_type,
                "source_ats": "icims",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "_filters_applied": filters,
            }
            matched_jobs.append(job_entry)

            if max_jobs and len(matched_jobs) >= max_jobs:
                break

        if max_jobs and len(matched_jobs) >= max_jobs:
            break

        if len(raw_jobs) < limit:
            break

        page += 1

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available if total_available > 0 else len(matched_jobs),
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Dispatch iCIMS job fetching for a company based on configuration:
    - Jibe / iCIMS Candidate Experience API (e.g. AMD)
    - TalentBrew custom portal (e.g. ARM Experienced Portal)
    - Standard iCIMS portal (*.icims.com)
    """
    logger.info(f"Fetching jobs from {company['name']} (iCIMS)")

    portal_type = company.get("portal_type", "").lower()

    if portal_type == "jibe" or company.get("api_url") or "amd" in company.get("name", "").lower():
        return fetch_jibe_icims_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif company.get("search_url") or company.get("career_site_url") or portal_type == "experienced":
        return fetch_talentbrew_icims_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    else:
        return fetch_standard_icims_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )

