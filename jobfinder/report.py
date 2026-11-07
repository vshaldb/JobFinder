"""
HTML Report Generator:
Renders fetched jobs data into a self-contained, interactive HTML dashboard.
"""

import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from jobfinder.applied import (
    get_applied_keys_set,
    is_job_applied,
    load_applied_jobs,
    save_applied_jobs,
)

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "template.html"


def sanitize_slug(name: str) -> str:
    """Convert company name to a safe HTML id/slug."""
    s = name.replace("&", "and").replace("/", "_").replace("\\", "_")
    s = "".join(c for c in s if c.isalnum() or c in (" ", "_", "-")).strip()
    return s.replace(" ", "_").lower()


def format_timestamp(iso_str: Optional[str]) -> str:
    """Format an ISO timestamp or fallback to current UTC time."""
    if iso_str:
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.strftime("%B %d, %Y at %H:%M:%S UTC")
        except Exception:
            return iso_str
    return datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M:%S UTC")


def get_location_tags(location: str) -> List[str]:
    """Map a raw location string to canonical tech-hub / city tag(s)."""
    if not location or not location.strip():
        return ["Other / Unspecified"]
    loc_lower = location.lower()
    tags = []
    if "bangalore" in loc_lower or "bengaluru" in loc_lower:
        tags.append("Bengaluru / Bangalore")
    if "hyderabad" in loc_lower:
        tags.append("Hyderabad")
    if "pune" in loc_lower:
        tags.append("Pune")
    if "noida" in loc_lower:
        tags.append("Noida / Greater Noida")
    if "gurgaon" in loc_lower or "gurugram" in loc_lower:
        tags.append("Gurgaon / Gurugram")
    if "chennai" in loc_lower:
        tags.append("Chennai")
    if "ahmedabad" in loc_lower or "sanand" in loc_lower or "gujarat" in loc_lower:
        tags.append("Ahmedabad / Gujarat")
    if "mumbai" in loc_lower:
        tags.append("Mumbai")
    if "delhi" in loc_lower and "noida" not in loc_lower:
        tags.append("Delhi / NCR")
    if "remote" in loc_lower or "virtual" in loc_lower or "home" in loc_lower or "mobile" in loc_lower:
        tags.append("Remote / Work from Home")

    if not tags:
        # For other cities (e.g. San Jose, Austin, Munich, Singapore)
        first_clean = location.split(";")[0].split(",")[0].strip()
        tags.append(first_clean if first_clean else location.strip())
    return tags


def render_apply_cell(
    url: str,
    title: str,
    company: str,
    job_id: str,
    job_id_full: Optional[str] = None,
    is_applied: bool = False,
) -> str:
    """
    Render the Apply / Applied action cell.
    If the job is already marked as applied in applied_jobs.json, it displays
    an Applied badge instead of the Apply button (with an optional unmark action).
    Otherwise, it renders the Apply ↗ link along with a quick 'Mark' action.
    """
    escaped_comp = html.escape(company, quote=True)
    escaped_jid = html.escape(str(job_id), quote=True)
    escaped_jid_full = html.escape(str(job_id_full or job_id), quote=True)
    escaped_title = html.escape(title, quote=True)
    escaped_url = html.escape(url or "#", quote=True)

    if is_applied:
        return (
            f'<div class="apply-action-group is-applied" '
            f'data-company="{escaped_comp}" data-jobid="{escaped_jid}" data-jobid-full="{escaped_jid_full}" '
            f'data-role="{escaped_title}" data-url="{escaped_url}">\n'
            f'  <span class="badge-applied" title="Marked as applied in applied_jobs.json">\n'
            f'    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>\n'
            f'    Applied\n'
            f'  </span>\n'
            f'  <button type="button" class="btn-toggle-apply btn-unmark-apply" title="Click to unmark applied status" aria-label="Unmark applied">\n'
            f'    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>\n'
            f'  </button>\n'
            f'</div>'
        )
    else:
        apply_link = (
            f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer" class="btn-apply" title="Apply for {escaped_title}">Apply ↗</a>'
            if url and url != "#"
            else '<span class="text-muted">N/A</span>'
        )
        return (
            f'<div class="apply-action-group not-applied" '
            f'data-company="{escaped_comp}" data-jobid="{escaped_jid}" data-jobid-full="{escaped_jid_full}" '
            f'data-role="{escaped_title}" data-url="{escaped_url}">\n'
            f'  {apply_link}\n'
            f'  <button type="button" class="btn-toggle-apply btn-mark-apply" title="Mark this role as applied in applied_jobs.json" aria-label="Mark applied">\n'
            f'    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>\n'
            f'    <span class="btn-mark-text">Mark</span>\n'
            f'  </button>\n'
            f'</div>'
        )


def build_merged_section(
    sorted_results: List[dict],
    total_companies: int,
    total_jobs: int,
    applied_keys: Optional[Set[str]] = None,
) -> str:
    """Build a unified single-table HTML section containing all jobs from all companies."""
    merged_jobs: List[dict] = []
    for r in sorted_results:
        comp_name = r.get("company", "Unknown")
        slug = sanitize_slug(comp_name)
        ats = r.get("ats") or (r.get("jobs", [{}])[0].get("source_ats") if r.get("jobs") else "Careers") or "Careers"
        for j in r.get("jobs", []):
            job_copy = dict(j)
            job_copy["company"] = comp_name
            job_copy["slug"] = slug
            job_copy["ats"] = ats
            merged_jobs.append(job_copy)

    # Sort newest posted jobs first by default (smaller posted_days_ago first)
    merged_jobs.sort(
        key=lambda x: (
            x.get("posted_days_ago") if x.get("posted_days_ago") is not None else 999999,
            x.get("company", "").lower(),
            (x.get("title") or "").lower(),
        )
    )

    rows_html: List[str] = []
    if merged_jobs:
        for idx, job in enumerate(merged_jobs, 1):
            comp_name = job["company"]
            slug = job["slug"]
            ats = job.get("ats", "Careers")
            ats_lower = ats.lower()
            if "workday" in ats_lower:
                badge_class = "badge-ats-workday"
            elif "eightfold" in ats_lower:
                badge_class = "badge-ats-eightfold"
            elif "greenhouse" in ats_lower:
                badge_class = "badge-ats-greenhouse"
            elif "icims" in ats_lower:
                badge_class = "badge-ats-icims"
            elif "rippling" in ats_lower:
                badge_class = "badge-ats-rippling"
            elif "ashby" in ats_lower:
                badge_class = "badge-ats-ashby"
            elif "lever" in ats_lower:
                badge_class = "badge-ats-lever"
            else:
                badge_class = "badge-ats-default"

            title = job.get("title", "Untitled Position")
            job_id = job.get("job_id", "N/A")
            job_id_full = job.get("job_id_full") or job_id
            location = job.get("location", "Not specified")
            posted_on = job.get("posted_on", "")
            posted_days = job.get("posted_days_ago")
            url = job.get("url", "#")
            loc_tags = get_location_tags(location)
            loc_tags_attr = "|".join(loc_tags)
            days_attr = str(posted_days) if posted_days is not None else "999999"
            jid_tooltip = f' title="Full ID: {html.escape(str(job_id_full), quote=True)}"' if str(job_id_full) != str(job_id) else ''

            if posted_on:
                if posted_days is not None:
                    days_text = f"{posted_days}d ago" if posted_days > 0 else "Today"
                    posted_cell = (
                        f'<span class="posted-date">{html.escape(str(posted_on))}</span> '
                        f'<span class="posted-relative">({html.escape(days_text)})</span>'
                    )
                else:
                    posted_cell = f'<span class="posted-date">{html.escape(str(posted_on))}</span>'
            else:
                posted_cell = '<span class="text-muted">N/A</span>'

            is_applied = is_job_applied(comp_name, job_id, job_id_full, applied_keys)
            apply_btn = render_apply_cell(url, title, comp_name, job_id, job_id_full, is_applied)
            applied_attr = "true" if is_applied else "false"
            row_applied_cls = " row-applied" if is_applied else ""

            company_cell = (
                f'<div class="company-cell-wrapper">\n'
                f'  <span class="company-name-text">{html.escape(comp_name)}</span>\n'
                f'  <span class="badge {badge_class}">{html.escape(ats.upper())}</span>\n'
                f'</div>'
            )

            rows_html.append(
                f'<tr class="job-row{row_applied_cls}" '
                f'data-company="{html.escape(comp_name, quote=True)}" '
                f'data-slug="{slug}" '
                f'data-title="{html.escape(title, quote=True)}" '
                f'data-location="{html.escape(location, quote=True)}" '
                f'data-loc-tags="{html.escape(loc_tags_attr, quote=True)}" '
                f'data-date="{html.escape(str(posted_on), quote=True)}" '
                f'data-days="{days_attr}" '
                f'data-applied="{applied_attr}" '
                f'data-orig-idx="{idx}">\n'
                f'  <td class="col-sno">{idx}</td>\n'
                f'  <td class="col-company">{company_cell}</td>\n'
                f'  <td class="col-title"><span class="role-name">{html.escape(title)}</span></td>\n'
                f'  <td class="col-jobid"><code{jid_tooltip}>{html.escape(str(job_id))}</code></td>\n'
                f'  <td class="col-location">{html.escape(location)}</td>\n'
                f'  <td class="col-posted">{posted_cell}</td>\n'
                f'  <td class="col-apply">{apply_btn}</td>\n'
                f'</tr>'
            )
    else:
        rows_html.append(
            '<tr class="no-jobs-row">\n'
            '  <td colspan="7" class="empty-state">No jobs found across any company.</td>\n'
            '</tr>'
        )

    rows_html.append(
        '<tr class="no-match-row" style="display: none;">\n'
        '  <td colspan="7" class="empty-state">No jobs matching current filters.</td>\n'
        '</tr>'
    )

    return f"""
    <section class="company-card merged-card" id="merged-table-card">
      <div class="company-header merged-header">
        <div class="company-title-area">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: var(--primary);">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="3" y1="9" x2="21" y2="9"></line>
            <line x1="9" y1="21" x2="9" y2="9"></line>
          </svg>
          <h2 class="company-name">Merged Job Board (All Companies)</h2>
          <span class="badge badge-ats-default">{total_companies} Companies</span>
        </div>
        <div class="header-right">
          <span class="badge badge-count" id="merged-badge-count">{total_jobs} jobs</span>
        </div>
      </div>
      <div class="table-responsive company-body">
        <table class="jobs-table">
          <thead>
            <tr>
              <th class="col-sno">S.No</th>
              <th class="col-company">
                <div class="th-content">
                  <span>Company</span>
                  <button type="button" class="btn-sort" data-sort="company" title="Sort by Company (A-Z / Z-A)">
                    <svg class="sort-icon icon-unsorted" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 15 5 5 5-5M7 9l5-5 5 5"/></svg>
                    <svg class="sort-icon icon-asc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 14 5-5 5 5"/></svg>
                    <svg class="sort-icon icon-desc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg>
                  </button>
                </div>
              </th>
              <th>
                <div class="th-content">
                  <span>Role Name</span>
                  <button type="button" class="btn-sort" data-sort="title" title="Sort by Role Name (A-Z / Z-A)">
                    <svg class="sort-icon icon-unsorted" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 15 5 5 5-5M7 9l5-5 5 5"/></svg>
                    <svg class="sort-icon icon-asc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 14 5-5 5 5"/></svg>
                    <svg class="sort-icon icon-desc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg>
                  </button>
                </div>
              </th>
              <th>Job ID</th>
              <th>
                <div class="th-content">
                  <span>Location</span>
                  <button type="button" class="btn-sort" data-sort="location" title="Sort by Location (A-Z / Z-A)">
                    <svg class="sort-icon icon-unsorted" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 15 5 5 5-5M7 9l5-5 5 5"/></svg>
                    <svg class="sort-icon icon-asc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 14 5-5 5 5"/></svg>
                    <svg class="sort-icon icon-desc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg>
                  </button>
                </div>
              </th>
              <th>
                <div class="th-content">
                  <span>Posted Date</span>
                  <button type="button" class="btn-sort" data-sort="date" title="Sort by Posted Date (Newest / Oldest)">
                    <svg class="sort-icon icon-unsorted" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 15 5 5 5-5M7 9l5-5 5 5"/></svg>
                    <svg class="sort-icon icon-asc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 14 5-5 5 5"/></svg>
                    <svg class="sort-icon icon-desc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg>
                  </button>
                </div>
              </th>
              <th style="text-align: center;">Link to Apply</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows_html)}
          </tbody>
        </table>
      </div>
    </section>
    """


def generate_html_report(
    results: List[dict],
    filters: dict,
    run_started_at: str,
    output_dir: Path,
) -> Path:
    """
    Generate an interactive HTML report from job search results using the HTML template.

    Parameters:
    - results: List of company result dicts containing jobs, company name, ats, etc.
    - filters: Active search filters dictionary.
    - run_started_at: Timestamp when search started.
    - output_dir: Directory where index.html should be written.

    Returns:
    - Path to the generated index.html file.
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found at: {TEMPLATE_PATH}")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    # Sort results alphabetically by company name
    sorted_results = sorted(results, key=lambda x: x.get("company", "").lower())

    # Load current applied jobs tracking data
    applied_jobs = load_applied_jobs()
    applied_keys = get_applied_keys_set(applied_jobs)
    try:
        save_applied_jobs(applied_jobs)
    except Exception as e:
        logger.debug(f"Failed to sync applied_jobs.js: {e}")

    # Calculate count of applied jobs present in current results
    applied_in_results = 0
    for r in sorted_results:
        cname = r.get("company", "")
        for j in r.get("jobs", []):
            if is_job_applied(cname, j.get("job_id", ""), j.get("job_id_full"), applied_keys):
                applied_in_results += 1

    total_companies = len(sorted_results)
    total_jobs = sum(len(r.get("jobs", [])) for r in sorted_results)

    # 1. Build Filter Chips HTML
    chips_html: List[str] = []
    if filters:
        for k, v in filters.items():
            if v not in ("", [], None):
                display_val = ", ".join(v) if isinstance(v, list) else str(v)
                label = k.replace("_", " ").title()
                chips_html.append(
                    f'<span class="chip"><strong>{html.escape(label)}:</strong> {html.escape(display_val)}</span>'
                )
    if not chips_html:
        chips_html.append('<span class="chip">Default (All active)</span>')
    filter_chips_str = "\n".join(chips_html)

    # 2. Build Location Multi-select options
    location_counts: Dict[str, int] = {}
    for r in sorted_results:
        for j in r.get("jobs", []):
            loc_tags = get_location_tags(j.get("location", ""))
            for tag in loc_tags:
                location_counts[tag] = location_counts.get(tag, 0) + 1

    sorted_locations = sorted(
        location_counts.keys(),
        key=lambda x: (-location_counts[x], x.lower())
    )

    loc_options_html: List[str] = []
    for loc_name in sorted_locations:
        cnt = location_counts[loc_name]
        loc_options_html.append(
            f'<label class="multiselect-option" data-loc-name="{html.escape(loc_name.lower())}">\n'
            f'  <input type="checkbox" class="loc-checkbox" value="{html.escape(loc_name)}" checked>\n'
            f'  <span class="option-label">{html.escape(loc_name)}</span>\n'
            f'  <span class="option-count">{cnt}</span>\n'
            f'</label>'
        )
    location_options_str = "\n".join(loc_options_html)

    # 3. Build Company Select Options
    options_html: List[str] = []
    options_html.append(f'<option value="all">All Companies ({total_jobs} jobs)</option>')

    for r in sorted_results:
        comp_name = r.get("company", "Unknown")
        slug = sanitize_slug(comp_name)
        job_count = len(r.get("jobs", []))
        options_html.append(
            f'<option value="{html.escape(slug)}">{html.escape(comp_name)} ({job_count} jobs)</option>'
        )
    company_options_str = "\n".join(options_html)

    # 4. Build Company Sections & Tables
    sections_html: List[str] = []

    for r in sorted_results:
        comp_name = r.get("company", "Unknown")
        slug = sanitize_slug(comp_name)
        jobs = r.get("jobs", [])
        job_count = len(jobs)
        ats = r.get("ats") or (jobs[0].get("source_ats") if jobs else "Careers") or "Careers"
        ats_lower = ats.lower()

        # ATS badge class
        if "workday" in ats_lower:
            badge_class = "badge-ats-workday"
        elif "eightfold" in ats_lower:
            badge_class = "badge-ats-eightfold"
        elif "greenhouse" in ats_lower:
            badge_class = "badge-ats-greenhouse"
        elif "icims" in ats_lower:
            badge_class = "badge-ats-icims"
        elif "rippling" in ats_lower:
            badge_class = "badge-ats-rippling"
        elif "ashby" in ats_lower:
            badge_class = "badge-ats-ashby"
        elif "lever" in ats_lower:
            badge_class = "badge-ats-lever"
        else:
            badge_class = "badge-ats-default"

        # Build table rows
        rows_html: List[str] = []
        if jobs:
            for idx, job in enumerate(jobs, 1):
                title = job.get("title", "Untitled Position")
                job_id = job.get("job_id", "N/A")
                job_id_full = job.get("job_id_full") or job_id
                location = job.get("location", "Not specified")
                posted_on = job.get("posted_on", "")
                posted_days = job.get("posted_days_ago")
                url = job.get("url", "#")
                loc_tags = get_location_tags(location)
                loc_tags_attr = "|".join(loc_tags)
                days_attr = str(posted_days) if posted_days is not None else "999999"
                jid_tooltip = f' title="Full ID: {html.escape(str(job_id_full), quote=True)}"' if str(job_id_full) != str(job_id) else ''

                # Format posted date
                if posted_on:
                    if posted_days is not None:
                        days_text = f"{posted_days}d ago" if posted_days > 0 else "Today"
                        posted_cell = (
                            f'<span class="posted-date">{html.escape(str(posted_on))}</span> '
                            f'<span class="posted-relative">({html.escape(days_text)})</span>'
                        )
                    else:
                        posted_cell = f'<span class="posted-date">{html.escape(str(posted_on))}</span>'
                else:
                    posted_cell = '<span class="text-muted">N/A</span>'

                is_applied = is_job_applied(comp_name, job_id, job_id_full, applied_keys)
                apply_btn = render_apply_cell(url, title, comp_name, job_id, job_id_full, is_applied)
                applied_attr = "true" if is_applied else "false"
                row_applied_cls = " row-applied" if is_applied else ""

                rows_html.append(
                    f'<tr class="job-row{row_applied_cls}" '
                    f'data-title="{html.escape(title, quote=True)}" '
                    f'data-location="{html.escape(location, quote=True)}" '
                    f'data-loc-tags="{html.escape(loc_tags_attr, quote=True)}" '
                    f'data-date="{html.escape(str(posted_on), quote=True)}" '
                    f'data-days="{days_attr}" '
                    f'data-applied="{applied_attr}" '
                    f'data-orig-idx="{idx}">\n'
                    f'  <td class="col-sno">{idx}</td>\n'
                    f'  <td class="col-title"><span class="role-name">{html.escape(title)}</span></td>\n'
                    f'  <td class="col-jobid"><code{jid_tooltip}>{html.escape(str(job_id))}</code></td>\n'
                    f'  <td class="col-location">{html.escape(location)}</td>\n'
                    f'  <td class="col-posted">{posted_cell}</td>\n'
                    f'  <td class="col-apply">{apply_btn}</td>\n'
                    f'</tr>'
                )
        else:
            error_note = f" &mdash; Error: {html.escape(r.get('error'))}" if r.get("error") else ""
            rows_html.append(
                f'<tr class="no-jobs-row">\n'
                f'  <td colspan="6" class="empty-state">No jobs found for this company{error_note}.</td>\n'
                f'</tr>'
            )

        # Always include a hidden no-match row for when search filter hides all job rows
        rows_html.append(
            f'<tr class="no-match-row" style="display: none;">\n'
            f'  <td colspan="6" class="empty-state">No jobs matching current filters in {html.escape(comp_name)}.</td>\n'
            f'</tr>'
        )

        section = f"""
    <section class="company-card" id="company-card-{slug}" data-slug="{slug}" data-company="{html.escape(comp_name)}" data-ats="{html.escape(ats)}">
      <div class="company-header" data-toggle="collapse" title="Click to expand/collapse table">
        <div class="company-title-area">
          <button type="button" class="company-collapse-btn" aria-expanded="true" title="Toggle Table for {html.escape(comp_name)}">
            <svg class="chevron-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          <h2 class="company-name">{html.escape(comp_name)}</h2>
          <span class="badge {badge_class}">{html.escape(ats.upper())}</span>
          <span class="badge badge-count">{job_count} jobs</span>
        </div>
      </div>
      <div class="table-responsive company-body">
        <table class="jobs-table">
          <thead>
            <tr>
              <th class="col-sno">S.No</th>
              <th>Role Name</th>
              <th>Job ID</th>
              <th>
                <div class="th-content">
                  <span>Location</span>
                  <button type="button" class="btn-sort" data-sort="location" title="Sort by Location (A-Z / Z-A)">
                    <svg class="sort-icon icon-unsorted" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 15 5 5 5-5M7 9l5-5 5 5"/></svg>
                    <svg class="sort-icon icon-asc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 14 5-5 5 5"/></svg>
                    <svg class="sort-icon icon-desc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg>
                  </button>
                </div>
              </th>
              <th>
                <div class="th-content">
                  <span>Posted Date</span>
                  <button type="button" class="btn-sort" data-sort="date" title="Sort by Posted Date (Newest / Oldest)">
                    <svg class="sort-icon icon-unsorted" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 15 5 5 5-5M7 9l5-5 5 5"/></svg>
                    <svg class="sort-icon icon-asc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 14 5-5 5 5"/></svg>
                    <svg class="sort-icon icon-desc" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m7 10 5 5 5-5"/></svg>
                  </button>
                </div>
              </th>
              <th style="text-align: center;">Link to Apply</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows_html)}
          </tbody>
        </table>
      </div>
    </section>
        """
        sections_html.append(section)

    company_sections_str = "\n".join(sections_html)

    # 5. Build Unified Merged Section
    merged_section_str = build_merged_section(
        sorted_results, total_companies, total_jobs, applied_keys=applied_keys
    )

    # 6. Fill in template placeholders
    rendered = template
    rendered = rendered.replace("{{PAGE_TITLE}}", "JobFinder Opportunities")
    rendered = rendered.replace("{{RUN_TIMESTAMP}}", format_timestamp(run_started_at))
    rendered = rendered.replace("{{FILTER_CHIPS}}", filter_chips_str)
    rendered = rendered.replace("{{TOTAL_COMPANIES}}", str(total_companies))
    rendered = rendered.replace("{{TOTAL_JOBS}}", str(total_jobs))
    rendered = rendered.replace("{{APPLIED_JOBS_COUNT}}", str(applied_in_results))
    rendered = rendered.replace("{{TOTAL_APPLIED_STORED}}", str(len(applied_jobs)))
    rendered = rendered.replace("{{APPLIED_JOBS_JSON}}", json.dumps(applied_jobs, ensure_ascii=False))
    rendered = rendered.replace("{{COMPANY_OPTIONS}}", company_options_str)
    rendered = rendered.replace("{{LOCATION_OPTIONS}}", location_options_str)
    rendered = rendered.replace("{{COMPANY_SECTIONS}}", company_sections_str)
    rendered = rendered.replace("{{MERGED_SECTION}}", merged_section_str)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "index.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    logger.info(f"Generated HTML report at: {report_path}")
    return report_path
