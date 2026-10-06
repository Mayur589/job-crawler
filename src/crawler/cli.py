"""Rich CLI interface for Job Crawler."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from crawler.engine import CrawlEngine
from crawler.matcher import JobMatcher
from crawler.models import CrawlStats, JobRecord, JobStatus
from crawler.storage import JobStorage

console = Console()


def get_score_badge(score: float) -> str:
    """Format score with color badges."""
    if score >= 6.0:
        return f"[bold green]{score:.1f}[/bold green] 🔥"
    elif score >= 4.0:
        return f"[bold cyan]{score:.1f}[/bold cyan] ⭐"
    elif score >= 3.0:
        return f"[yellow]{score:.1f}[/yellow]"
    return f"[dim]{score:.1f}[/dim]"


def get_status_badge(status: JobStatus) -> str:
    """Format job status with color badges."""
    mapping = {
        JobStatus.NEW: "[bold green]NEW[/bold green]",
        JobStatus.SEEN: "[dim cyan]SEEN[/dim cyan]",
        JobStatus.APPLIED: "[bold magenta]APPLIED[/bold magenta]",
        JobStatus.SAVED: "[bold yellow]SAVED[/bold yellow]",
        JobStatus.IGNORED: "[dim]IGNORED[/dim]",
        JobStatus.CLOSED: "[red]CLOSED[/red]",
    }
    return mapping.get(status, status.value)


async def run_crawl_command(args: argparse.Namespace) -> None:
    """Run crawler across all enabled sources."""
    console.print(Panel.fit("[bold blue]Starting Job Crawler Run[/bold blue]", border_style="blue"))
    engine = CrawlEngine()

    def on_source_start(source_name: str) -> None:
        console.print(f"[cyan]→ Crawling source:[/cyan] [bold]{source_name}[/bold]...")

    def on_job_matched(job: JobRecord, is_new: bool) -> None:
        tag = "[green][NEW MATCH][/green]" if is_new else "[yellow][UPDATED][/yellow]"
        kw_str = ", ".join(job.matched_keywords[:3])
        if len(job.matched_keywords) > 3:
            kw_str += f" (+{len(job.matched_keywords) - 3})"
        console.print(
            f"  {tag} {get_score_badge(job.score)} [bold]{job.title}[/bold] @ [cyan]{job.company}[/cyan] ({kw_str})"
        )

    def on_source_complete(stats: CrawlStats) -> None:
        if stats.errors:
            console.print(f"  [red]⚠️ Encountered {len(stats.errors)} error(s) in {stats.source}[/red]")
        console.print(
            f"  [dim]Finished {stats.source}: fetched {stats.total_fetched}, matched {stats.total_matched} ({stats.total_new} new)[/dim]\n"
        )

    results = await engine.run(
        on_source_start=on_source_start,
        on_job_matched=on_job_matched,
        on_source_complete=on_source_complete,
        mark_closed=not args.no_close,
    )

    # Print summary table
    table = Table(title="Crawl Session Summary", border_style="dim")
    table.add_column("Source", style="bold")
    table.add_column("Fetched", justify="right")
    table.add_column("Matched", justify="right")
    table.add_column("New Added", justify="right", style="green")
    table.add_column("Updated", justify="right", style="yellow")
    table.add_column("Errors", justify="right", style="red")

    tot_fetched = sum(s.total_fetched for s in results)
    tot_matched = sum(s.total_matched for s in results)
    tot_new = sum(s.total_new for s in results)
    tot_updated = sum(s.total_updated for s in results)
    tot_errors = sum(len(s.errors) for s in results)

    for s in results:
        table.add_row(
            s.source,
            str(s.total_fetched),
            str(s.total_matched),
            str(s.total_new),
            str(s.total_updated),
            str(len(s.errors)),
        )

    table.add_section()
    table.add_row("Total", str(tot_fetched), str(tot_matched), str(tot_new), str(tot_updated), str(tot_errors), style="bold")
    console.print(table)
    console.print(f"\n[bold green]✓ Done![/bold green] Found {tot_new} new relevant roles. Run `uv run job-crawler list` to inspect.")


def run_list_command(args: argparse.Namespace) -> None:
    """List matching jobs from the database."""
    storage = JobStorage()
    jobs = storage.list_jobs(
        status=args.status,
        min_score=args.min_score,
        search_query=args.search,
        source=args.source,
        remote_only=args.remote,
        india_only=args.india,
        india_or_remote=args.india_or_remote,
        limit=args.limit,
    )

    if not jobs:
        console.print("[yellow]No matching jobs found with the given filters.[/yellow]")
        return

    filter_desc = ""
    if args.india_or_remote:
        filter_desc = " [bold cyan](India or Remote)[/bold cyan]"
    elif args.india:
        filter_desc = " [bold green](India only)[/bold green]"
    elif args.remote:
        filter_desc = " [bold blue](Remote only)[/bold blue]"

    table = Table(title=f"Jobs in Database ({len(jobs)} shown){filter_desc}", border_style="cyan")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Score", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Title", style="bold white", max_width=32)
    table.add_column("Company", style="cyan", max_width=18)
    table.add_column("Location", style="yellow", max_width=22)
    table.add_column("Keywords", style="green", max_width=25)
    table.add_column("Link / URL", style="blue", max_width=35, overflow="ellipsis")

    for j in jobs:
        kw_display = ", ".join(j.matched_keywords[:3])
        if len(j.matched_keywords) > 3:
            kw_display += f" +{len(j.matched_keywords) - 3}"

        loc_prefix = ""
        if j.is_india:
            loc_prefix = "🇮🇳 "
        elif j.is_remote:
            loc_prefix = "🌐 "

        table.add_row(
            j.id[:8],
            get_score_badge(j.score),
            get_status_badge(j.status),
            j.title,
            j.company,
            loc_prefix + (j.location or "Unspecified"),
            kw_display,
            j.url,
        )

    console.print(table)
    console.print("[dim]Tip: Run `uv run job-crawler show <ID>` to view job description & matched phrases.[/dim]")


def run_show_command(args: argparse.Namespace) -> None:
    """Show details for a specific job."""
    storage = JobStorage()
    job = storage.get_job(args.job_id)
    if not job:
        console.print(f"[red]Error: Job with ID prefix '{args.job_id}' not found.[/red]")
        sys.exit(1)

    # If it was NEW, automatically update to SEEN
    if job.status == JobStatus.NEW:
        storage.update_status(job.id, JobStatus.SEEN)
        job.status = JobStatus.SEEN

    panel_title = f"{job.title} @ {job.company}"
    console.print(Panel(f"[bold]{panel_title}[/bold]", style="bold blue"))

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column(style="bold cyan")
    info_table.add_column()

    info_table.add_row("Job ID:", job.id)
    info_table.add_row("Status:", get_status_badge(job.status))
    info_table.add_row("Score:", get_score_badge(job.score))
    info_table.add_row("Location:", ("🌐 Remote" if job.is_remote else "") + f" {job.location}")
    info_table.add_row("Source:", job.source)
    info_table.add_row("Apply URL:", f"[underline blue]{job.url}[/underline blue]")
    info_table.add_row("First Seen:", job.first_seen_at.strftime("%Y-%m-%d %H:%M UTC"))
    info_table.add_row("Last Seen:", job.last_seen_at.strftime("%Y-%m-%d %H:%M UTC"))
    info_table.add_row("Keywords:", ", ".join(job.matched_keywords))

    console.print(info_table)
    console.print("\n[bold]Description Snippet:[/bold]")
    snippet = job.description[:1200]
    if len(job.description) > 1200:
        snippet += "\n\n... [truncated, open apply URL for complete posting] ..."
    console.print(Panel(snippet, border_style="dim"))
    console.print(f"[dim]Commands: `uv run job-crawler set-status {job.id[:8]} applied` | `saved` | `ignored`[/dim]")


def run_set_status_command(args: argparse.Namespace) -> None:
    """Update status of a job."""
    storage = JobStorage()
    try:
        status_enum = JobStatus(args.status.lower())
    except ValueError:
        valid = ", ".join(s.value for s in JobStatus)
        console.print(f"[red]Invalid status '{args.status}'. Valid choices: {valid}[/red]")
        sys.exit(1)

    updated = storage.update_status(args.job_id, status_enum)
    if updated:
        console.print(f"[green]✓ Status of job '{args.job_id}' updated to '{status_enum.value}'.[/green]")
    else:
        console.print(f"[red]Job with ID '{args.job_id}' not found.[/red]")
        sys.exit(1)


def run_stats_command(args: argparse.Namespace) -> None:
    """Print database statistics."""
    storage = JobStorage()
    stats = storage.get_stats()

    console.print(Panel.fit("[bold blue]Job Crawler Database Statistics[/bold blue]", border_style="blue"))
    console.print(f"Total Tracked Jobs: [bold]{stats['total_jobs']}[/bold] (Remote: [cyan]{stats['remote_count']}[/cyan])\n")

    # Status table
    table_status = Table(title="Jobs by Status", border_style="dim")
    table_status.add_column("Status")
    table_status.add_column("Count", justify="right")
    for status, count in stats["status_counts"].items():
        table_status.add_row(status.upper(), str(count))
    console.print(table_status)
    console.print()

    # Sources table
    table_sources = Table(title="Jobs by Source", border_style="dim")
    table_sources.add_column("Source")
    table_sources.add_column("Count", justify="right")
    for src, count in sorted(stats["source_counts"].items(), key=lambda x: x[1], reverse=True):
        table_sources.add_row(src, str(count))
    console.print(table_sources)
    console.print()

    # Top keywords
    if stats["top_keywords"]:
        table_kw = Table(title="Top Matched Keywords", border_style="dim")
        table_kw.add_column("Keyword")
        table_kw.add_column("Matches", justify="right")
        for kw, count in stats["top_keywords"]:
            table_kw.add_row(kw, str(count))
        console.print(table_kw)


def run_export_command(args: argparse.Namespace) -> None:
    """Export jobs to CSV or JSON."""
    storage = JobStorage()
    fmt = args.format.lower()
    out = args.output

    if fmt == "csv":
        if not out:
            out = "data/jobs_export_india.csv" if args.india else ("data/jobs_export_india_remote.csv" if args.india_or_remote else "data/jobs_export.csv")
        count = storage.export_csv(out, india_only=args.india, india_or_remote=args.india_or_remote)
        console.print(f"[green]✓ Exported {count} jobs to CSV: [bold]{out}[/bold][/green]")
    elif fmt == "json":
        if not out:
            out = "data/jobs_export_india.json" if args.india else ("data/jobs_export_india_remote.json" if args.india_or_remote else "data/jobs_export.json")
        count = storage.export_json(out, india_only=args.india, india_or_remote=args.india_or_remote)
        console.print(f"[green]✓ Exported {count} jobs to JSON: [bold]{out}[/bold][/green]")
    else:
        console.print("[red]Invalid export format. Choose 'csv' or 'json'.[/red]")
        sys.exit(1)


def run_test_match_command(args: argparse.Namespace) -> None:
    """Test matching rules on a sample title and description."""
    matcher = JobMatcher()
    res = matcher.evaluate(title=args.title, description=args.description or "", location=args.location or "")

    console.print(Panel.fit(f"[bold]Evaluating: '{args.title}'[/bold]", border_style="cyan"))
    console.print(f"Is Match: {'[bold green]YES[/bold green]' if res.is_match else '[bold red]NO[/bold red]'}")
    console.print(f"Total Score: {get_score_badge(res.score)}")
    console.print(f"Is Remote: {res.is_remote}")
    if res.is_rejected:
        console.print(f"[bold red]Rejected:[/bold red] {res.rejection_reason}")

    if res.match_details:
        table = Table(title="Matched Keyword Details", border_style="dim")
        table.add_column("Keyword")
        table.add_column("Target")
        table.add_column("Weight", justify="right")
        table.add_column("Snippet")
        for m in res.match_details:
            table.add_row(m.keyword, m.matched_in, f"{m.weight:+.1f}", m.snippet)
        console.print(table)


def main() -> None:
    """CLI entry point dispatcher."""
    parser = argparse.ArgumentParser(description="Keyword-Based Job Crawler & Pipeline")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # crawl
    crawl_parser = subparsers.add_parser("crawl", help="Run crawler across enabled sources")
    crawl_parser.add_argument("--no-close", action="store_true", help="Do not mark unseen jobs as closed")

    # list
    list_parser = subparsers.add_parser("list", help="List matched jobs")
    list_parser.add_argument("--status", choices=["new", "seen", "applied", "saved", "ignored", "closed"], help="Filter by status")
    list_parser.add_argument("--min-score", type=float, help="Minimum score filter")
    list_parser.add_argument("--search", type=str, help="Search term in title, company, location, or keywords")
    list_parser.add_argument("--source", type=str, help="Filter by source (e.g. greenhouse:gitlab)")
    list_parser.add_argument("--remote", action="store_true", help="Show remote-only jobs")
    list_parser.add_argument("--india", action="store_true", help="Show India-based jobs only")
    list_parser.add_argument("--india-or-remote", action="store_true", help="Show jobs located in India or Remote")
    list_parser.add_argument("--limit", type=int, default=30, help="Max results to return (default: 30)")

    # show
    show_parser = subparsers.add_parser("show", help="Show details for a specific job")
    show_parser.add_argument("job_id", type=str, help="Job ID (or first 8 chars)")

    # set-status
    status_parser = subparsers.add_parser("set-status", help="Update job status")
    status_parser.add_argument("job_id", type=str, help="Job ID (or first 8 chars)")
    status_parser.add_argument("status", type=str, help="New status: new, seen, applied, saved, ignored")

    # stats
    subparsers.add_parser("stats", help="Display crawler database statistics")

    # export
    export_parser = subparsers.add_parser("export", help="Export jobs to CSV or JSON")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Export format (default: csv)")
    export_parser.add_argument("--output", "-o", type=str, help="Output file path")
    export_parser.add_argument("--india", action="store_true", help="Export India-based jobs only")
    export_parser.add_argument("--india-or-remote", action="store_true", help="Export jobs located in India or Remote")

    # test-match
    test_parser = subparsers.add_parser("test-match", help="Test keyword rules against a job title and description")
    test_parser.add_argument("title", type=str, help="Job title to test")
    test_parser.add_argument("--description", "-d", type=str, default="", help="Job description to test")
    test_parser.add_argument("--location", "-l", type=str, default="", help="Location to test")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "crawl":
        asyncio.run(run_crawl_command(args))
    elif args.command == "list":
        run_list_command(args)
    elif args.command == "show":
        run_show_command(args)
    elif args.command == "set-status":
        run_set_status_command(args)
    elif args.command == "stats":
        run_stats_command(args)
    elif args.command == "export":
        run_export_command(args)
    elif args.command == "test-match":
        run_test_match_command(args)


if __name__ == "__main__":
    main()
