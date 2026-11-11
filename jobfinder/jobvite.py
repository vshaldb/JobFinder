"""
Jobvite Careers Fetcher
Fetches job postings from Jobvite-hosted career boards (e.g. SiMa.ai).
Endpoint: https://jobs.jobvite.com/{board_slug}?nl=1
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

JOBVITE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
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
        "ahmedabad",
    ],
    "bangalore": ["bangalore", "bengaluru"],
    "bengaluru": ["bangalore", "bengaluru"],
    "gurgaon": ["gurugram", "gurgaon"],
    "gurugram": ["gurugram", "gurgaon"],
}


def parse_jobvite_date(date_str: str) -> Tuple[str, Optional[int]]:
    """Parse ISO YYYY-MM-DD date string from Jobvite JSON-LD."""
    if not date_str:
        return "", None
    clean = str(date_str).strip()[:10]
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
        return clean, days_ago
    except Exception as e:
        logger.debug(f"Could not parse Jobvite date '{date_str}': {e}")
        return clean, None


def matches_location(job_loc: str, target_location: str) -> bool:
    """Check if job location matches target location filter."""
    if not target_location:
        return True
    target_clean = target_location.lower().strip()
    synonyms = LOCATION_SYNONYMS.get(target_clean, [target_clean])
    loc_lower = (job_loc or "").lower()
    return target_clean in loc_lower or any(syn in loc_lower for syn in synonyms)


def matches_keyword(title: str, keyword: str) -> bool:
    """Check if job title matches target keyword filter."""
    if not keyword:
        return True
    title_lower = title.lower()
    kw_lower = keyword.lower().strip()
    if kw_lower in title_lower:
        return True
    return any(w in title_lower for w in kw_lower.split())


def _clean_whitespace(text: str) -> str:
    """Strip tags, unescape HTML entities, and collapse whitespace."""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    unescaped = html.unescape(no_tags)
    cleaned = re.sub(r"\s+", " ", unescaped).strip()
    return re.sub(r"\s*,\s*", ", ", cleaned)


def _parse_job_listings(html_text: str, board_slug: str) -> List[dict]:
    """Extract jobs and department headings from Jobvite ?nl=1 board HTML."""
    parsed: List[dict] = []
    seen_ids = set()

    # Track department headings (<h4 ...>...</h4>) interleaved with job anchors
    token_pattern = re.compile(
        r'<h4[^>]*>(.*?)</h4>'
        r'|<a[^>]*href=["\'](/' + re.escape(board_slug) + r'/job/([^"\'?#]+))[^"\']*["\'][^>]*>(.*?)</a>',
        re.S | re.I,
    )

    current_dept = ""
    for match in token_pattern.finditer(html_text):
        dept_raw, href, job_id, anchor_inner = match.groups()
        if dept_raw is not None:
            current_dept = _clean_whitespace(dept_raw)
            continue

        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title_match = re.search(
            r'class=["\'][^"\']*jv-job-list-name[^"\']*["\'][^>]*>(.*?)</div>',
            anchor_inner,
            re.S | re.I,
        )
        loc_match = re.search(
            r'class=["\'][^"\']*jv-job-list-location[^"\']*["\'][^>]*>(.*?)</div>',
            anchor_inner,
            re.S | re.I,
        )

        title = _clean_whitespace(title_match.group(1) if title_match else anchor_inner)
        location = _clean_whitespace(loc_match.group(1) if loc_match else "")

        if not title:
            continue

        parsed.append({
            "job_id": job_id,
            "title": title,
            "location": location,
            "department": current_dept,
            "external_path": href,
        })

    return parsed


def _enrich_job_details(board_slug: str, jobs: List[dict], session: requests.Session) -> None:
    """Concurrently fetch Jobvite detail pages to extract datePosted & employmentType."""

    def fetch_detail(job: dict) -> None:
        jid = job.get("job_id", "")
        if not jid:
            return
        url = f"https://jobs.jobvite.com/{board_slug}/job/{jid}?nl=1"
        try:
            resp = session.get(url, headers=JOBVITE_HEADERS, timeout=15)
            if resp.status_code != 200:
                return
            for ld_raw in re.findall(
                r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                resp.text,
                re.S | re.I,
            ):
                try:
                    data = json.loads(ld_raw.strip())
                    if isinstance(data, dict) and data.get("@type") == "JobPosting":
                        posted_raw = data.get("datePosted") or ""
                        if posted_raw:
                            posted_on, days_ago = parse_jobvite_date(posted_raw)
                            job["posted_on"] = posted_on
                            job["posted_days_ago"] = days_ago
                        emp = data.get("employmentType")
                        if emp:
                            emp_val = ", ".join(emp) if isinstance(emp, list) else str(emp)
                            job["employment_type"] = emp_val.strip()
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Failed Jobvite detail fetch for {jid}: {e}")

    if not jobs:
        return

    with ThreadPoolExecutor(max_workers=min(len(jobs), 8)) as executor:
        list(executor.map(fetch_detail, jobs))


def fetch_company_jobs(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """Fetch jobs from a Jobvite career board."""
    board_slug = company.get("board_slug") or company.get("tenant") or company["name"].lower()
    board_url = f"https://jobs.jobvite.com/{board_slug}?nl=1"

    keyword_filter = filters.get("keyword", "")
    location_filter = (filters.get("location") or "").strip()

    logger.info(f"Fetching jobs from {company['name']} (Jobvite: {board_slug})")

    try:
        resp = session.get(board_url, headers=JOBVITE_HEADERS, timeout=25)
        resp.raise_for_status()
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

    raw_jobs = _parse_job_listings(resp.text, board_slug)
    matched_prelim: List[dict] = []

    for raw in raw_jobs:
        if not matches_keyword(raw["title"], keyword_filter):
            continue
        if not matches_location(raw["location"], location_filter):
            continue

        jid = raw["job_id"]
        matched_prelim.append({
            "company": company["name"],
            "title": raw["title"],
            "job_id": jid,
            "location": raw["location"],
            "employment_type": raw.get("department", ""),
            "posted_on": "",
            "posted_days_ago": None,
            "url": f"https://jobs.jobvite.com/{board_slug}/job/{jid}?nl=1",
            "external_path": raw["external_path"],
            "remote_type": "Remote" if "remote" in raw["location"].lower() else "",
            "source_ats": "jobvite",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "_filters_applied": filters,
        })

    total_matching = len(matched_prelim)

    if max_jobs and not posted_within_days and len(matched_prelim) > max_jobs:
        matched_prelim = matched_prelim[:max_jobs]

    _enrich_job_details(board_slug, matched_prelim, session)

    final_jobs: List[dict] = []
    for job in matched_prelim:
        if posted_within_days is not None and posted_within_days > 0:
            if job["posted_days_ago"] is not None and job["posted_days_ago"] > posted_within_days:
                continue
        final_jobs.append(job)
        if max_jobs and len(final_jobs) >= max_jobs:
            break

    return {
        "company": company["name"],
        "success": True,
        "error": None,
        "total_available": total_matching if location_filter else len(raw_jobs),
        "jobs_fetched": len(final_jobs),
        "jobs": final_jobs,
    }
