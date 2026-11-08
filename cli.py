#!/usr/bin/env python3
"""
JobFinder CLI
=============
Fetches job postings from multiple companies careers portals across
Workday, Eightfold.ai, Greenhouse, and iCIMS.

Usage examples
--------------
  # Fetch all jobs from all enabled companies (defaults to India location)
  python cli.py fetch

  # Filter by keyword (India location still applied by default)
  python cli.py fetch --keyword "software engineer"

  # Change location
  python cli.py fetch --location "Bangalore"

  # Fetch globally (remove the India default)
  python cli.py fetch --no-location

  # Filter by posted date (last 7 days only)
  python cli.py fetch --posted-within 7

  # Specific companies only (comma-separated)
  python cli.py fetch --company "NVIDIA,Qualcomm,Tenstorrent,ARM"

  # Filter by ATS platform
  python cli.py fetch --ats icims
  python cli.py fetch --ats eightfold
  python cli.py fetch --ats greenhouse
  python cli.py fetch --ats workday

  # Filter by domain
  python cli.py fetch --domain semiconductor

  # Combine filters
  python cli.py fetch --keyword "VLSI" --domain semiconductor --posted-within 14 --max-jobs 10

  # List configured companies
  python cli.py companies

  # Add a new company interactively
  python cli.py add-company
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich import print as rprint

from jobfinder.config import filter_companies, load_companies, list_company_names
from jobfinder.output import save_results
from jobfinder.fetcher import fetch_jobs_for_company
from jobfinder.applied import (
    load_applied_jobs,
    mark_job_applied,
    unmark_job_applied,
)
from jobfinder.server import run_server_forever

console = Console()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# CLI root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("1.1.0", prog_name="jobfinder")
def cli() -> None:
    """
    \b
    ╔══════════════════════════════════════════════════════════╗
    ║        JobFinder — Multi-Portal Careers CLI              ║
    ║ Supported ATS: Workday | Eightfold | Greenhouse | iCIMS  ║
    ║        Rippling | Ashby | Lever | Google | Meta          ║
    ║                    Apple | Amazon                        ║
    ╚══════════════════════════════════════════════════════════╝

    Fetch job postings from multiple corporate career portals and save them
    as structured JSON files in the job_data/ directory.
    """


# ---------------------------------------------------------------------------
# fetch command
# ---------------------------------------------------------------------------

@cli.command("fetch")
@click.option(
    "--keyword", "-k",
    default="",
    show_default=True,
    help="Search keyword (e.g. 'software engineer', 'verification', 'analog').",
)
@click.option(
    "--location", "-l",
    default="India",
    show_default=True,
    help=(
        "Location filter. Defaults to 'India'. "
        "Use --no-location to fetch globally."
    ),
)
@click.option(
    "--no-location",
    is_flag=True,
    default=False,
    help="Disable the default India location filter and fetch all locations.",
)
@click.option(
    "--posted-within", "-d",
    "posted_within_days",
    default=None,
    type=int,
    help=(
        "Only include jobs posted within this many days. "
        "E.g. --posted-within 7 keeps only jobs from the last week."
    ),
)
@click.option(
    "--company", "-c",
    default="",
    help=(
        "Comma-separated company names to fetch from. "
        "E.g. --company 'NVIDIA,Qualcomm,Tenstorrent'. "
        "Defaults to all enabled companies."
    ),
)
@click.option(
    "--ats", "-a",
    default="all",
    show_default=True,
    help="Filter by ATS provider ('all', 'workday', 'eightfold', 'greenhouse', 'icims', 'rippling', 'ashby', 'lever', 'google', 'meta', 'apple', 'amazon').",
)
@click.option(
    "--domain", "-D",
    default="",
    help=(
        "Filter companies by domain tag (e.g. 'semiconductor', 'tech'). "
        "Combine with other filters for finer control."
    ),
)
@click.option(
    "--job-family", "-j",
    default="",
    show_default=True,
    help="Job family / department filter (where supported).",
)
@click.option(
    "--time-type", "-t",
    default="",
    show_default=True,
    help="Employment time type filter (e.g. 'Full_Time', 'Part_Time').",
)
@click.option(
    "--max-jobs", "-m",
    default=0,
    type=int,
    show_default=True,
    help="Maximum jobs to fetch per company (0 = unlimited).",
)
@click.option(
    "--companies-file", "-f",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to a custom companies.json config file.",
)
@click.option(
    "--output-dir", "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory to write output JSON (default: job_data/).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose/debug logging.")
def fetch(
    keyword: str,
    location: str,
    no_location: bool,
    posted_within_days: Optional[int],
    company: str,
    ats: str,
    domain: str,
    job_family: str,
    time_type: str,
    max_jobs: int,
    companies_file: Optional[Path],
    output_dir: Optional[Path],
    verbose: bool,
) -> None:
    """Fetch job postings across corporate career portals."""

    setup_logging(verbose)

    # Parse comma-separated company names
    company_list = [c.strip() for c in company.split(",") if c.strip()] if company else []

    # Resolve effective location
    effective_location = "" if no_location else location

    # ── Build filters dict ───────────────────────────────────────────────
    filters: dict = {
        "keyword": keyword,
        "location": effective_location,
        "companies": company_list,
        "ats": ats,
        "domain": domain,
        "job_family": job_family,
        "time_type": time_type,
        "max_jobs_per_company": max_jobs,
        "posted_within_days": posted_within_days,
    }
    # Remove empty/falsy values for cleaner JSON
    filters_clean = {
        k: v for k, v in filters.items()
        if v not in ("", [], 0, None) and not (k == "ats" and v == "all")
    }

    # ── Load & filter companies ───────────────────────────────────────────
    all_companies = load_companies(companies_file)
    target_companies = filter_companies(
        all_companies,
        names=company_list if company_list else None,
        enabled_only=True,
        ats=ats if ats != "all" else None,
        domain=domain if domain else None,
    )

    if not target_companies:
        console.print("[bold red]No matching enabled companies found.[/bold red]")
        console.print(
            "Run [bold]jobfinder companies[/bold] to see available companies, "
            "or check your filters."
        )
        sys.exit(1)

    # ── Display run summary ───────────────────────────────────────────────
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]JobFinder[/bold cyan]  —  Careers Portal Fetcher\n"
            f"[dim]Fetching from {len(target_companies)} company/ies across ATS platforms[/dim]",
            border_style="cyan",
        )
    )

    if filters_clean:
        console.print("\n[bold]Active Filters:[/bold]")
        _FILTER_LABELS = {
            "keyword": "Keyword",
            "location": "Location",
            "posted_within_days": "Posted within (days)",
            "companies": "Companies",
            "ats": "ATS Provider",
            "domain": "Domain",
            "job_family": "Job Family",
            "time_type": "Time Type",
            "max_jobs_per_company": "Max jobs/company",
        }
        for k, v in filters_clean.items():
            label = _FILTER_LABELS.get(k, k)
            if k == "posted_within_days":
                console.print(f"  [green]{label}[/green]: {v} days")
            else:
                console.print(f"  [green]{label}[/green]: {v}")
    else:
        console.print("\n[dim]No filters applied — fetching all available jobs.[/dim]")
    console.print()

    # ── Run fetches ───────────────────────────────────────────────────────
    run_started_at = datetime.utcnow().isoformat() + "Z"
    results = []

    with requests.Session() as session:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            overall = progress.add_task(
                "Overall", total=len(target_companies)
            )

            for company in target_companies:
                task = progress.add_task(
                    f"[cyan]{company['name']}[/cyan] [dim]({company.get('ats', '')})[/dim]",
                    total=None,
                )

                result = fetch_jobs_for_company(
                    company=company,
                    filters=filters_clean,
                    session=session,
                    max_jobs=max_jobs if max_jobs > 0 else None,
                    posted_within_days=posted_within_days,
                )
                result["ats"] = company.get("ats", "")
                results.append(result)

                if result["success"]:
                    progress.update(
                        task,
                        description=(
                            f"[green]✓ {company['name']}[/green] "
                            f"({result['jobs_fetched']} jobs)"
                        ),
                        completed=result["jobs_fetched"],
                        total=result["total_available"] or result["jobs_fetched"],
                    )
                else:
                    progress.update(
                        task,
                        description=(
                            f"[red]✗ {company['name']}[/red] "
                            f"— {result['error']}"
                        ),
                        completed=0,
                        total=1,
                    )

                progress.advance(overall)

    # ── Save output ───────────────────────────────────────────────────────
    out_dir = save_results(
        results=results,
        filters=filters_clean,
        run_started_at=run_started_at,
        output_dir=output_dir,
    )

    # ── Print result table ────────────────────────────────────────────────
    console.print()
    table = Table(title="Fetch Results", show_lines=True)
    table.add_column("Company", style="bold")
    table.add_column("ATS", style="dim")
    table.add_column("Status")
    table.add_column("Available", justify="right")
    table.add_column("Fetched", justify="right", style="cyan")
    table.add_column("Error")

    total_fetched = 0
    for r, comp in zip(results, target_companies):
        status = "[green]✓ OK[/green]" if r["success"] else "[red]✗ FAIL[/red]"
        table.add_row(
            r["company"],
            comp.get("ats", "unknown"),
            status,
            str(r["total_available"]),
            str(r["jobs_fetched"]),
            r.get("error") or "",
        )
        total_fetched += r["jobs_fetched"]

    console.print(table)
    console.print(
        f"\n[bold green]✓ {total_fetched} jobs saved to:[/bold green] [underline]{out_dir}[/underline]"
    )
    html_report = out_dir / "index.html"
    if html_report.exists():
        console.print(
            f"[bold green]✓ Web report available at:[/bold green] [cyan underline]file://{html_report.resolve()}[/cyan underline]"
        )
        console.print(
            f"[dim]💡 Live Tracking: Run [bold cyan]python cli.py serve[/bold cyan] to view with live application sync to applied_jobs.json.[/dim]\n"
        )
    else:
        console.print()


# ---------------------------------------------------------------------------
# companies command
# ---------------------------------------------------------------------------

@cli.command("companies")
@click.option(
    "--companies-file", "-f",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to a custom companies.json config file.",
)
@click.option(
    "--ats", "-a",
    default="all",
    show_default=True,
    help="Filter by ATS provider ('all', 'workday', 'eightfold', 'greenhouse', 'icims', 'rippling', 'ashby', 'lever', 'google', 'meta', 'apple', 'amazon').",
)
@click.option(
    "--domain", "-D",
    default="",
    help="Filter by domain tag (e.g. 'semiconductor', 'tech').",
)
@click.option("--all", "show_all", is_flag=True, help="Show disabled companies too.")
def companies_cmd(
    companies_file: Optional[Path],
    ats: str,
    domain: str,
    show_all: bool,
) -> None:
    """List all configured companies."""
    all_companies = load_companies(companies_file)

    table = Table(title="Configured Companies", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Company", style="bold")
    table.add_column("ATS", style="cyan")
    table.add_column("Target / Board / Tenant")
    table.add_column("Domain")
    table.add_column("Enabled")

    shown = 0
    for i, c in enumerate(all_companies, start=1):
        enabled = c.get("enabled", True)
        if not show_all and not enabled:
            continue
        if ats and ats.lower() != "all" and c.get("ats", "").lower() != ats.lower():
            continue
        if domain and c.get("domain", "").lower() != domain.lower():
            continue

        c_ats = c.get("ats", "")
        if c_ats == "workday":
            target = f"{c.get('tenant')}.{c.get('datacenter')} / {c.get('site_name')}"
        elif c_ats in ("eightfold", "eightfold.ai"):
            if c.get("host"):
                target = f"{c.get('host')} ({c.get('extra_params', {}).get('domain', '')})"
            else:
                target = f"{c.get('subdomain')}.eightfold.ai ({c.get('domain_param')})"
        elif c_ats == "greenhouse":
            target = f"board: {c.get('board_token')}"
        elif c_ats in ("icims", "talentbrew"):
            sub = c.get("subdomain") or c.get("tenant", "")
            target = f"{sub}.icims.com ({c.get('portal_type', 'standard')})"
        elif c_ats == "rippling":
            target = f"ats.rippling.com/{c.get('board_slug', '')}"
        elif c_ats == "ashby":
            target = f"ashbyhq.com/{c.get('board_token', '')}"
        elif c_ats == "lever":
            target = f"lever.co/{c.get('site_name', '')}"
        elif c_ats == "google":
            target = "careers.google.com"
        elif c_ats == "meta":
            target = "metacareers.com"
        elif c_ats == "apple":
            target = f"jobs.apple.com ({c.get('locale', 'en-in')})"
        elif c_ats == "amazon":
            target = f"amazon.jobs ({c.get('category', 'software-development')})"
        else:
            target = c.get("tenant", "")

        enabled_str = "[green]✓[/green]" if enabled else "[red]✗[/red]"
        table.add_row(
            str(i),
            c["name"],
            c_ats,
            target,
            c.get("domain", ""),
            enabled_str,
        )
        shown += 1

    console.print(table)
    console.print(f"\n[dim]{shown} companies shown.[/dim]")
    if not show_all:
        console.print(
            "[dim]Use [bold]--all[/bold] to include disabled companies.[/dim]"
        )


# ---------------------------------------------------------------------------
# add-company command
# ---------------------------------------------------------------------------

@cli.command("add-company")
@click.option(
    "--companies-file", "-f",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to the companies.json file to update.",
)
def add_company(companies_file: Optional[Path]) -> None:
    """Interactively add a new company to the config (Workday, Eightfold, or Greenhouse)."""
    from jobfinder.config import DEFAULT_CONFIG_PATH

    config_path = companies_file or DEFAULT_CONFIG_PATH

    console.print(
        "\n[bold cyan]Add a new Company to JobFinder[/bold cyan]\n"
        "Supported platforms: [green]workday[/green] | [green]eightfold[/green] | [green]greenhouse[/green] | [green]icims[/green] | [green]rippling[/green] | [green]ashby[/green] | [green]lever[/green]\n"
    )

    name = click.prompt("Company name", type=str)
    ats_type = click.prompt(
        "ATS Provider",
        type=click.Choice(["workday", "eightfold", "greenhouse", "icims", "rippling", "ashby", "lever"], case_sensitive=False),
        default="workday",
    ).lower()

    domain = click.prompt("Domain category (e.g. semiconductor, tech)", default="semiconductor")

    new_entry = {
        "name": name,
        "ats": ats_type,
        "domain": domain,
        "enabled": True,
    }

    if ats_type == "workday":
        tenant = click.prompt("Workday tenant (e.g. nvidia, intel)", type=str)
        datacenter = click.prompt("Workday datacenter (e.g. wd1, wd3, wd5, wd12)", type=str)
        site_name = click.prompt("Workday site name (e.g. External, External_Careers)", type=str)
        new_entry.update({
            "tenant": tenant.strip(),
            "datacenter": datacenter.strip(),
            "site_name": site_name.strip(),
        })
    elif ats_type == "eightfold":
        subdomain = click.prompt("Eightfold subdomain (e.g. qualcomm for qualcomm.eightfold.ai)", type=str)
        domain_param = click.prompt("Eightfold corporate domain (e.g. qualcomm.com)", type=str)
        career_site_url = click.prompt(
            "Career site URL prefix",
            default=f"https://{subdomain.strip()}.eightfold.ai",
        )
        new_entry.update({
            "subdomain": subdomain.strip(),
            "domain_param": domain_param.strip(),
            "career_site_url": career_site_url.strip(),
        })
    elif ats_type == "greenhouse":
        board_token = click.prompt("Greenhouse board token (e.g. tenstorrent, sambanovasystems)", type=str)
        new_entry.update({
            "board_token": board_token.strip(),
        })
    elif ats_type == "icims":
        subdomain = click.prompt("iCIMS subdomain (e.g. experienced-arm for experienced-arm.icims.com)", type=str)
        portal_type = click.prompt("Portal type (e.g. experienced, standard)", default="experienced", type=str)
        career_site_url = click.prompt("Career site URL prefix (optional)", default=f"https://{subdomain.strip()}.icims.com", type=str)
        new_entry.update({
            "subdomain": subdomain.strip(),
            "portal_type": portal_type.strip(),
            "career_site_url": career_site_url.strip(),
        })
    elif ats_type == "rippling":
        board_slug = click.prompt("Rippling board slug (e.g. tylsemi)", type=str)
        new_entry.update({
            "board_slug": board_slug.strip(),
            "career_site_url": f"https://ats.rippling.com/{board_slug.strip()}/jobs",
        })
    elif ats_type == "ashby":
        board_token = click.prompt("Ashby board token (e.g. cerebras, d-matrix)", type=str)
        new_entry.update({
            "board_token": board_token.strip(),
            "career_site_url": f"https://jobs.ashbyhq.com/{board_token.strip()}",
        })
    elif ats_type == "lever":
        site_name = click.prompt("Lever site name (e.g. nuvacore, eliyan)", type=str)
        new_entry.update({
            "site_name": site_name.strip(),
            "career_site_url": f"https://jobs.lever.co/{site_name.strip()}",
        })

    enabled = click.confirm("Enable this company?", default=True)
    new_entry["enabled"] = enabled

    # Load existing list
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            companies = json.load(f)
    else:
        companies = []

    # Check for duplicates
    existing_names = [c["name"].lower() for c in companies]
    if name.lower() in existing_names:
        if not click.confirm(
            f"A company named '{name}' already exists. Overwrite?", default=False
        ):
            console.print("[yellow]Aborted.[/yellow]")
            return
        companies = [c for c in companies if c["name"].lower() != name.lower()]

    companies.append(new_entry)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(companies, f, indent=2, ensure_ascii=False)

    console.print(
        f"\n[green]✓ Added [bold]{name}[/bold] ({ats_type}) to {config_path}[/green]\n"
    )


# ---------------------------------------------------------------------------
# Applied jobs tracking commands
# ---------------------------------------------------------------------------

@cli.command("applied")
@click.option("--company", "-c", help="Filter applied jobs by company name")
def applied_cmd(company: Optional[str]) -> None:
    """List all jobs marked as already applied in applied_jobs.json."""
    applied = load_applied_jobs()
    if company:
        applied = [j for j in applied if company.lower() in j.get("company", "").lower()]

    if not applied:
        msg = f"No applied jobs found{' for ' + company if company else ''}."
        console.print(f"[yellow]{msg}[/yellow]")
        console.print("Mark jobs in the web report or run: [bold]python cli.py apply --company <name> --job-id <id>[/bold]\n")
        return

    table = Table(
        title=f"Applied Jobs ({len(applied)} total)",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("S.No", justify="right", style="dim", width=6)
    table.add_column("Company", style="bold green", min_width=16)
    table.add_column("Job ID", style="bold yellow", min_width=14)
    table.add_column("Role Name", style="white", min_width=32)
    table.add_column("Applied Date", justify="center", style="dim", width=20)

    for idx, item in enumerate(applied, 1):
        table.add_row(
            str(idx),
            item.get("company", "Unknown"),
            str(item.get("job_id", "N/A")),
            item.get("role") or "—",
            item.get("applied_at") or "—",
        )

    console.print(table)
    console.print(f"[dim]Tracking file: applied_jobs.json ({len(applied)} recorded)[/dim]\n")


@cli.command("apply")
@click.option("--company", "-c", required=True, help="Company name (e.g. ARM, NVIDIA)")
@click.option("--job-id", "-j", required=True, help="Job ID / Requisition ID")
@click.option("--role", "-r", default="", help="Role name / title (optional, for reference)")
def apply_cmd(company: str, job_id: str, role: str) -> None:
    """Mark a job as applied in applied_jobs.json."""
    is_new, item = mark_job_applied(company=company, job_id=job_id, role=role)
    if is_new:
        console.print(f"[bold green]✓ Marked job [cyan]{job_id}[/cyan] at [yellow]{company}[/yellow] as applied![/bold green]")
        if role:
            console.print(f"  Role: {role}")
    else:
        console.print(f"[cyan]Job [bold]{job_id}[/bold] at [bold]{company}[/bold] was already marked as applied.[/cyan]")
    console.print(f"[dim]Saved to applied_jobs.json[/dim]\n")


@cli.command("unapply")
@click.option("--company", "-c", required=True, help="Company name")
@click.option("--job-id", "-j", required=True, help="Job ID to unmark")
def unapply_cmd(company: str, job_id: str) -> None:
    """Remove a job from applied_jobs.json."""
    removed = unmark_job_applied(company=company, job_id=job_id)
    if removed:
        console.print(f"[bold green]✓ Removed job [cyan]{job_id}[/cyan] at [yellow]{company}[/yellow] from applied_jobs.json.[/bold green]\n")
    else:
        console.print(f"[yellow]No applied job found matching company '{company}' and job ID '{job_id}'.[/yellow]\n")


@cli.command("serve")
@click.option("--port", "-p", default=8000, type=int, help="Port to listen on (default: 8000)")
@click.option("--host", "-h", default="127.0.0.1", type=str, help="Host to bind (default: 127.0.0.1)")
def serve_cmd(port: int, host: str) -> None:
    """
    Start the local web server to view reports with live applied jobs sync.
    Directly syncs applied marks between the browser report and applied_jobs.json.
    """
    console.print(
        Panel.fit(
            f"[bold green]JobFinder Local Server[/bold green]\n\n"
            f"• Web UI:      [bold cyan]http://{host}:{port}/[/bold cyan]\n"
            f"• Applied API: [dim]http://{host}:{port}/api/applied[/dim]\n\n"
            f"[dim]Any jobs marked in the browser will immediately write to applied_jobs.json on disk.\n"
            f"Refreshing the browser will always load the latest applied_jobs.json records.[/dim]",
            title="JobFinder Dashboard Server",
            border_style="green",
        )
    )
    run_server_forever(host=host, port=port)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
