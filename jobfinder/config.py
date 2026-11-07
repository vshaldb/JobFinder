"""
Company config loader.
Reads companies.json (next to this package's parent directory) and
provides helpers to filter / validate entries.
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "companies.json"


def load_companies(config_path: Optional[Path] = None) -> List[dict]:
    """Load the list of companies from the JSON config file."""
    path = config_path or DEFAULT_CONFIG_PATH

    if not path.exists():
        print(
            f"[ERROR] Company config file not found: {path}\n"
            "Please create it or use --companies-file to specify a path.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        try:
            companies = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in {path}: {e}", file=sys.stderr)
            sys.exit(1)

    return companies


def filter_companies(
    companies: List[dict],
    names: Optional[List[str]] = None,
    enabled_only: bool = True,
    ats: Optional[str] = None,
    domain: Optional[str] = None,
) -> List[dict]:
    """
    Filter company list.

    Args:
        companies:     Full list loaded from config.
        names:         If given, only include these company names (case-insensitive).
        enabled_only:  Skip companies with "enabled": false.
        ats:           Filter by ATS provider (e.g. 'workday', 'eightfold', 'greenhouse', 'icims', or 'all'/None for any).
        domain:        If given, only include companies with this domain tag
                       (e.g. "semiconductor", "tech").
    """
    result = []
    for c in companies:
        if ats and ats.lower() != "all":
            if c.get("ats", "").lower() != ats.lower():
                continue
        if enabled_only and not c.get("enabled", True):
            continue
        if names:
            if c["name"].lower() not in [n.lower() for n in names]:
                continue
        if domain:
            if c.get("domain", "").lower() != domain.lower():
                continue
        result.append(c)
    return result


def list_company_names(companies: List[dict]) -> List[str]:
    return [c["name"] for c in companies]
