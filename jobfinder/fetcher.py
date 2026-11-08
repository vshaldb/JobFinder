"""
Unified Job Fetcher Dispatcher
Routes company job fetching to the appropriate ATS module (Workday, Eightfold, Greenhouse, iCIMS).
"""

import logging
from typing import Optional
import requests

from jobfinder import workday
from jobfinder import eightfold
from jobfinder import greenhouse
from jobfinder import icims
from jobfinder import rippling
from jobfinder import ashby
from jobfinder import lever
from jobfinder import google
from jobfinder import meta
from jobfinder import apple
from jobfinder import amazon

logger = logging.getLogger(__name__)


def fetch_jobs_for_company(
    company: dict,
    filters: dict,
    session: requests.Session,
    max_jobs: Optional[int] = None,
    posted_within_days: Optional[int] = None,
) -> dict:
    """
    Dispatch job fetching to the appropriate ATS provider.
    Supported: 'workday', 'eightfold', 'greenhouse', 'icims', 'rippling', 'ashby', 'lever'.
    """
    ats = company.get("ats", "").lower()

    if ats == "workday":
        return workday.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats in ("eightfold", "eightfold.ai"):
        return eightfold.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "greenhouse":
        return greenhouse.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats in ("icims", "talentbrew"):
        return icims.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "rippling":
        return rippling.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "ashby":
        return ashby.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "lever":
        return lever.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "google":
        return google.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "meta":
        return meta.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "apple":
        return apple.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    elif ats == "amazon":
        return amazon.fetch_company_jobs(
            company=company,
            filters=filters,
            session=session,
            max_jobs=max_jobs,
            posted_within_days=posted_within_days,
        )
    else:
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

