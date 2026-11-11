"""
MediaTek Careers Fetcher
Fetches job postings from MediaTek's careers portal using its tRPC API.
Endpoint: https://careers.mediatek.com/api/trpc/job.getJobs
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

MEDIATEK_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Verified MediaTek India location IDs as fallback if SSR extraction changes
INDIA_CITY_MAP = {
    "noida": ("Noida, India", "0000009297"),
    "bangalore": ("Bangalore, India", "0000168800"),
    "bengaluru": ("Bangalore, India", "0000168800"),
    "mumbai": ("Mumbai, India", "9021"),
}

INDIA_CITIES = {"noida", "bangalore", "bengaluru", "mumbai"}
PAGE_LIMIT = 50
MAX_PAGES = 50


def parse_mediatek_date(date_str: str) -> Tuple[str, Optional[int]]:
    """Parse MediaTek ISO timestamp (e.g. '2026-11-04T16:00:00.000+00:00')."""
    if not date_str:
        return "", None
    clean = str(date_str).strip()[:10]
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
        return clean, days_ago
    except Exception as e:
        logger.debug(f"Could not parse MediaTek date '{date_str}': {e}")
        return clean, None


def matches_keyword(title: str, keyword: str) -> bool:
    """Client-side keyword filter."""
    if not keyword:
        return True
    title_lower = title.lower()
    kw_lower = keyword.lower().strip()
    if kw_lower in title_lower:
        return True
    return any(w in title_lower for w in kw_lower.split())


def _extract_location_options(session: requests.Session, portal_url: str) -> Dict[str, str]:
    """Scrape location label -> code mapping from Next.js /en/jobs SSR payload."""
    try:
        resp = session.get(portal_url, headers=MEDIATEK_HEADERS, timeout=20)
        if resp.status_code != 200:
            return {}
        unescaped = resp.text.replace('\\"', '"')
        m = re.search(r'"location"\s*:\s*(\[\s*\{[^\]]+\}\s*\])', unescaped)
        if not m:
            return {}
        items = json.loads(m.group(1))
        mapping: Dict[str, str] = {}
        for item in items:
            if isinstance(item, dict) and item.get("label") and item.get("value"):
                label = str(item["label"]).strip().lower()
                mapping[label] = str(item["value"]).strip()
        return mapping
    except Exception as e:
        logger.debug(f"MediaTek location extraction failed (using fallback map): {e}")
        return {}


def _resolve_location_codes(loc_map: Dict[str, str], target_location: str) -> Tuple[List[str], bool]:
    """Resolve target location string to MediaTek location IDs. Returns (codes, server_filtered)."""
    if not target_location:
        return [], False

    target_clean = target_location.lower().strip()
    if target_clean == "india":
        codes = []
        for city in ("bangalore", "noida", "mumbai"):
            code = loc_map.get(city) or INDIA_CITY_MAP[city][1]
            if code not in codes:
                codes.append(code)
        return codes, True

    # Direct city lookup
    lookup_name = "bangalore" if target_clean == "bengaluru" else target_clean
    matched_codes = []
    for label, code in loc_map.items():
        if lookup_name in label:
            matched_codes.append(code)
    if not matched_codes and lookup_name in INDIA_CITY_MAP:
        matched_codes.append(INDIA_CITY_MAP[lookup_name][1])

    if matched_codes:
        return list(dict.fromkeys(matched_codes)), True

    return [], False


def format_location(raw_city: str) -> str:
    """Clean trailing whitespace and append country for known Indian R&D hubs."""
    city = str(raw_city or "").strip()
    if not city:
        return ""
    if city.lower() in INDIA_CITIES:
        return f"{city}, India"
    return city


def normalize_job(raw: dict, company: dict, filters: dict) -> dict:
    """Normalize MediaTek tRPC job object to standardized JobFinder schema."""
    job_id = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()

    props = raw.get("properties") or {}
    loc_obj = props.get("location") or {}
    # Note MediaTek stores city name in location.code and numeric id in location.label
    raw_loc_name = str(loc_obj.get("code") or raw.get("location") or "").strip()
    display_loc = format_location(raw_loc_name)

    cat_obj = props.get("category") or {}
    category = str(cat_obj.get("label") or "").strip()

    posted_on, posted_days_ago = parse_mediatek_date(raw.get("publishedDate") or "")

    return {
        "company": company["name"],
        "title": title,
        "job_id": job_id,
        "location": display_loc,
        "employment_type": category,
        "posted_on": posted_on,
        "posted_days_ago": posted_days_ago,
        "url": f"https://careers.mediatek.com/en/jobs/{job_id}" if job_id else "https://careers.mediatek.com/en/jobs",
        "external_path": f"/en/jobs/{job_id}" if job_id else "",
        "remote_type": "Remote" if "remote" in raw_loc_name.lower() else "",
        "source_ats": "mediatek",
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
    """Fetch matching jobs from MediaTek Careers via its tRPC job.getJobs endpoint."""
    portal_url = company.get("career_site_url", "https://careers.mediatek.com/en/jobs")
    trpc_url = "https://careers.mediatek.com/api/trpc/job.getJobs"

    keyword_filter = (filters.get("keyword") or "").strip()
    location_filter = (filters.get("location") or "").strip()

    logger.info(f"Fetching jobs from {company['name']} (MediaTek tRPC)")

    loc_map = _extract_location_options(session, portal_url)
    loc_codes, server_filtered = _resolve_location_codes(loc_map, location_filter)

    if location_filter and not server_filtered:
        # Unmatched non-India location requested: fetch global or return empty cleanly after checking
        pass

    job_query_info = {"keywords": keyword_filter.split(), "relation": "OR"} if keyword_filter else {}

    matched_jobs: List[dict] = []
    seen_ids = set()
    total_available = 0

    for page in range(1, MAX_PAGES + 1):
        trpc_input = {
            "json": {
                "locales": "en_US",
                "page": page,
                "jobQueryInfo": job_query_info,
                "filters": {
                    "categorys": [],
                    "workExperiences": [],
                    "locations": loc_codes,
                    "programs": [],
                },
                "sortBy": "publishedDate",
                "order": "DESC",
                "limit": PAGE_LIMIT,
            }
        }

        try:
            resp = session.get(
                trpc_url,
                params={"input": json.dumps(trpc_input)},
                headers=MEDIATEK_HEADERS,
                timeout=25,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.exceptions.RequestException as e:
            err = f"tRPC request failed on page {page}: {e}"
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

        inner = ((payload.get("result") or {}).get("data") or {}).get("json") or {}
        if page == 1:
            pagination = inner.get("pagination") or {}
            total_available = int(pagination.get("total_items") or 0)

        raw_jobs = inner.get("jobs") or []
        if not raw_jobs:
            break

        for raw in raw_jobs:
            job = normalize_job(raw, company, filters)
            jid = job["job_id"]
            if not job["title"] or not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)

            if not matches_keyword(job["title"], keyword_filter):
                continue

            if location_filter and not server_filtered:
                if location_filter.lower() not in job["location"].lower():
                    continue

            if posted_within_days is not None and posted_within_days > 0:
                if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                    continue

            matched_jobs.append(job)
            if max_jobs and len(matched_jobs) >= max_jobs:
                break

        if max_jobs and len(matched_jobs) >= max_jobs:
            break

        if len(raw_jobs) < PAGE_LIMIT or (total_available > 0 and page * PAGE_LIMIT >= total_available):
            break

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_available if total_available > 0 else len(matched_jobs),
        "jobs_fetched": len(matched_jobs),
        "jobs": matched_jobs,
    }
