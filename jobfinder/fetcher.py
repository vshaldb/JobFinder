"""
Unified Job Fetcher Dispatcher
Routes company job fetching to the appropriate ATS module.
"""

import logging
from typing import Optional
import requests

from jobfinder import amazon
from jobfinder import apple
from jobfinder import ashby
from jobfinder import attrax
from jobfinder import eightfold
from jobfinder import google
from jobfinder import greenhouse
from jobfinder import icims
from jobfinder import jobvite
from jobfinder import lever
from jobfinder import mediatek
from jobfinder import meta
from jobfinder import oracle_hcm
from jobfinder import realtek
from jobfinder import rippling
from jobfinder import successfactors
from jobfinder import workday

logger = logging.getLogger(__name__)

ATS_DISPATCH = {
    "workday": workday,
    "eightfold": eightfold,
    "eightfold.ai": eightfold,
    "greenhouse": greenhouse,
    "icims": icims,
    "talentbrew": icims,
    "rippling": rippling,
    "ashby": ashby,
    "lever": lever,
    "google": google,
    "meta": meta,
    "apple": apple,
    "amazon": amazon,
    "oracle_hcm": oracle_hcm,
    "oracle": oracle_hcm,
    "successfactors": successfactors,
    "jobvite": jobvite,
    "attrax": attrax,
    "mediatek": mediatek,
    "realtek": realtek,
}


def fetch_jobs_for_company(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Dispatch job fetching to the appropriate ATS provider module.
    """
    ats = company.get("ats", "").lower()
    handler = ATS_DISPATCH.get(ats)

    if handler is not None:
        return handler.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )

    err = f"Unsupported ATS provider: '{ats}'"
    logger.error(f"{company.get('name')}: {err}")
    return {
        "company": company.get("name", "Unknown"),
        "success": False,
        "error": err,
        "total_available": 0,
        "jobs_fetched": 0,
        "jobs": [],
    }
