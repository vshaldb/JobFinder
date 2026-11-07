"""
JobFinder Applied Jobs Tracker
==============================
Tracks jobs that the user has marked as already applied.
Persists applied job records in applied_jobs.json in the project root.
Also syncs job_data/applied_jobs.js for static file:// support.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
APPLIED_JOBS_FILE = PROJECT_ROOT / "applied_jobs.json"
JOB_DATA_DIR = PROJECT_ROOT / "job_data"
APPLIED_JOBS_JS = JOB_DATA_DIR / "applied_jobs.js"


def normalize_key(company: str, job_id: str) -> str:
    """Generate a canonical lookup key from company name and job ID."""
    return f"{company.strip().lower()}:::{str(job_id).strip().lower()}"


def load_applied_jobs(file_path: Optional[Path] = None) -> List[dict]:
    """
    Load applied jobs from applied_jobs.json.
    Returns a list of dictionaries with keys: company, job_id, role, applied_at.
    """
    path = file_path or APPLIED_JOBS_FILE
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return list(data.values())
            return []
    except Exception as e:
        logger.error(f"Error reading applied jobs from {path}: {e}")
        return []


def save_applied_jobs(jobs: List[dict], file_path: Optional[Path] = None) -> None:
    """
    Save the list of applied jobs to applied_jobs.json.
    Also syncs job_data/applied_jobs.js for static browser viewing.
    """
    path = file_path or APPLIED_JOBS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write {path}: {e}")
        raise

    # Also sync job_data/applied_jobs.js for file:// execution
    try:
        JOB_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(APPLIED_JOBS_JS, "w", encoding="utf-8") as f:
            f.write("window.APPLIED_JOBS = " + json.dumps(jobs, indent=2, ensure_ascii=False) + ";\n")
    except Exception as e:
        logger.debug(f"Could not sync {APPLIED_JOBS_JS}: {e}")


def get_applied_keys_set(jobs: Optional[List[dict]] = None) -> Set[str]:
    """
    Return a set of normalized keys for all applied jobs.
    Includes both job_id and job_id_full if present.
    """
    if jobs is None:
        jobs = load_applied_jobs()
    keys: Set[str] = set()
    for item in jobs:
        comp = item.get("company", "")
        jid = item.get("job_id", "")
        jid_full = item.get("job_id_full", "")
        if comp and jid:
            keys.add(normalize_key(comp, jid))
        if comp and jid_full:
            keys.add(normalize_key(comp, jid_full))
    return keys


def is_job_applied(
    company: str,
    job_id: str,
    job_id_full: Optional[str] = None,
    applied_keys: Optional[Set[str]] = None,
) -> bool:
    """
    Check if a job is in the applied jobs list.
    Fast O(1) lookup using normalized company and job_id.
    """
    if not company or not job_id:
        return False
    if applied_keys is None:
        applied_keys = get_applied_keys_set()
    if normalize_key(company, job_id) in applied_keys:
        return True
    if job_id_full and normalize_key(company, job_id_full) in applied_keys:
        return True
    return False


def mark_job_applied(
    company: str,
    job_id: str,
    role: str = "",
    applied_at: Optional[str] = None,
    job_id_full: Optional[str] = None,
) -> Tuple[bool, dict]:
    """
    Mark a job as applied. Appends to applied_jobs.json if not already present.
    Returns (is_newly_added, job_dict).
    """
    if not company or not job_id:
        raise ValueError("Both company and job_id are required to mark a job as applied.")

    jobs = load_applied_jobs()
    target_key = normalize_key(company, job_id)
    target_full_key = normalize_key(company, job_id_full) if job_id_full else None

    # Check if already present
    for item in jobs:
        c = item.get("company", "")
        jid = item.get("job_id", "")
        jid_f = item.get("job_id_full", "")
        k = normalize_key(c, jid)
        kf = normalize_key(c, jid_f) if jid_f else None
        if k == target_key or (target_full_key and k == target_full_key) or (kf and kf == target_key):
            # Already exists, update role if provided and missing
            if role and not item.get("role"):
                item["role"] = role
                save_applied_jobs(jobs)
            return False, item

    # Add new entry
    new_entry = {
        "company": company.strip(),
        "job_id": str(job_id).strip(),
        "role": role.strip(),
        "applied_at": applied_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if job_id_full and str(job_id_full).strip() != str(job_id).strip():
        new_entry["job_id_full"] = str(job_id_full).strip()

    jobs.append(new_entry)
    save_applied_jobs(jobs)
    return True, new_entry


def unmark_job_applied(company: str, job_id: str) -> bool:
    """
    Unmark a job as applied. Removes from applied_jobs.json.
    Returns True if an entry was removed, False if not found.
    """
    jobs = load_applied_jobs()
    target_key = normalize_key(company, job_id)
    initial_count = len(jobs)

    filtered = []
    for item in jobs:
        c = item.get("company", "")
        jid = item.get("job_id", "")
        jid_f = item.get("job_id_full", "")
        k = normalize_key(c, jid)
        kf = normalize_key(c, jid_f) if jid_f else None
        if k == target_key or (kf and kf == target_key):
            continue
        filtered.append(item)

    if len(filtered) < initial_count:
        save_applied_jobs(filtered)
        return True
    return False

