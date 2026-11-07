"""
Output writer:
Saves per-company JSON files into job_data/ and generates index.html (cleared on every run).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from jobfinder.report import generate_html_report

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
JOB_DATA_DIR = PROJECT_ROOT / "job_data"


def sanitize_company_filename(name: str) -> str:
    """Convert company name to a safe filename slug (e.g. 'Procter & Gamble' -> 'Procter_and_Gamble')."""
    s = name.replace("&", "and").replace("/", "_").replace("\\", "_")
    s = "".join(c for c in s if c.isalnum() or c in (" ", "_", "-")).strip()
    return s.replace(" ", "_")


def clean_directory(directory: Path) -> int:
    """Delete all JSON and HTML files in the given directory. Returns count of deleted files."""
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return 0

    count = 0
    patterns = ["*.json", "*.html"]
    for pattern in patterns:
        for f in directory.glob(pattern):
            if f.name.startswith("applied_jobs"):
                continue
            try:
                f.unlink()
                count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {f}: {e}")
    return count


def save_results(
    results: List[dict],
    filters: dict,
    run_started_at: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Clear job_data/, write one JSON file per company, and generate interactive index.html.

    Each JSON file has the schema:
    {
        "company": "<Name>",
        "run_at": "<iso_timestamp>",
        "filters": {...},
        "total_available": <int>,
        "jobs_fetched": <int>,
        "jobs": [...]
    }

    Returns the output directory path.
    """
    job_dir = output_dir or JOB_DATA_DIR
    job_dir.mkdir(parents=True, exist_ok=True)

    # Clear previous run's files
    clean_directory(job_dir)

    run_time_iso = datetime.now(timezone.utc).isoformat()

    for r in results:
        company_name = r["company"]
        safe_name = sanitize_company_filename(company_name)

        payload = {
            "company": company_name,
            "run_at": run_time_iso,
            "filters": filters,
            "total_available": r.get("total_available", 0),
            "jobs_fetched": r.get("jobs_fetched", 0),
            "success": r.get("success", False),
            "error": r.get("error"),
            "jobs": r.get("jobs", []),
        }

        out_file = job_dir / f"{safe_name}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # Generate interactive HTML report
    try:
        generate_html_report(
            results=results,
            filters=filters,
            run_started_at=run_started_at,
            output_dir=job_dir,
        )
    except Exception as e:
        logger.error(f"Failed to generate HTML report: {e}", exc_info=True)

    return job_dir
