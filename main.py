#!/usr/bin/env python3
import sys
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich import box

from profile import build_or_load_profile
from scrapers.linkedin import search_linkedin_jobs
from scrapers.remoteok import search_remoteok_jobs
from scrapers.web_search import search_web_for_jobs
from scrapers.serpapi_jobs import search_serpapi_jobs, check_serpapi_available
from scrapers.naukri import search_naukri_jobs
from scrapers.indeed import search_indeed_jobs
from matcher import compute_relevance
from config import load_config, save_config

console = Console()


def run_scraper(name, scraper_func, query, location):
    try:
        results = scraper_func(query, location)
        return name, results
    except Exception as e:
        return name, []


def deduplicate(jobs):
    seen = set()
    unique = []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique


def search_jobs(query, location):
    scrapers = {
        "LinkedIn": search_linkedin_jobs,
        "Indeed": search_indeed_jobs,
        "Naukri": search_naukri_jobs,
        "RemoteOK": search_remoteok_jobs,
        "Web Search": search_web_for_jobs,
    }

    if check_serpapi_available():
        scrapers["Google Jobs"] = search_serpapi_jobs

    all_jobs = []
    source_counts = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Searching job sources...", total=len(scrapers))

        with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
            futures = {
                executor.submit(run_scraper, name, func, query, location): name
                for name, func in scrapers.items()
            }
            for future in as_completed(futures):
                name, jobs = future.result()
                unique = deduplicate(jobs)
                source_counts[name] = len(unique)
                progress.update(
                    task,
                    advance=1,
                    description=f"[green]Got {len(unique)} jobs from {name}",
                )
                all_jobs.extend(unique)
                time.sleep(0.1)

    return all_jobs, source_counts


def rank_jobs(jobs, profile):
    ranked = []
    for job in jobs:
        relevance = compute_relevance(job, profile)
        ranked.append((relevance["score"], job, relevance["reasons"]))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def display_results(ranked, source_counts, top_n=20):
    if not ranked:
        console.print("[yellow]No jobs found. Try broadening your search terms.[/yellow]")
        return

    summary_parts = [f"[cyan]{count}[/] from [bold]{name}[/]" for name, count in source_counts.items() if count > 0]
    summary = " | ".join(summary_parts)
    console.print(f"\n[bold]Found {len(ranked)} total jobs[/bold] — {summary}")

    ranked = [(s, j, r) for s, j, r in ranked if s > 0]

    if not ranked:
        console.print("[yellow]No jobs matched your profile sufficiently. Try broadening your search.[/yellow]")
        return

    def shorten_url(url, max_len=30):
        if not url:
            return ""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            display = f"{parsed.netloc}/{path}"
        else:
            display = parsed.netloc
        if len(display) > max_len:
            display = display[:max_len-3] + "..."
        return display

    table = Table(
        title="[bold]Top Matching Jobs[/bold]",
        box=box.SIMPLE,
        header_style="bold cyan",
        show_edge=False,
    )
    table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("Title", style="bold", width=22, overflow="ellipsis")
    table.add_column("Company", width=14, overflow="ellipsis")
    table.add_column("Source", width=8, no_wrap=True)
    table.add_column("Link", width=30, overflow="ellipsis")
    table.add_column("Match", justify="right", width=6, no_wrap=True)

    for i, (score, job, reasons) in enumerate(ranked[:top_n], 1):
        score_color = "green" if score >= 60 else "yellow" if score >= 25 else "red"
        url = job.get("url", "")
        table.add_row(
            str(i),
            job.get("title", "N/A"),
            job.get("company", "N/A"),
            job.get("source", "N/A"),
            f"[dim]{shorten_url(url)}[/dim]",
            f"[{score_color}]{score}%[/{score_color}]",
        )

    console.print(table)

    show_detail = Confirm.ask("Show details for a specific job?", default=False)
    if show_detail:
        while True:
            choice = Prompt.ask(
                "Enter job number to see details (or 'q' to quit)", default="q"
            )
            if choice.lower() == "q":
                break
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(ranked):
                    score, job, reasons = ranked[idx]
                    detail_panel = Panel(
                        f"[bold]{job.get('title', 'N/A')}[/bold]\n"
                        f"[cyan]Company:[/cyan] {job.get('company', 'N/A')}\n"
                        f"[cyan]Location:[/cyan] {job.get('location', 'N/A')}\n"
                        f"[cyan]Source:[/cyan] {job.get('source', 'N/A')}\n"
                        f"[cyan]URL:[/cyan] {job.get('url', 'N/A')}\n"
                        f"[cyan]Match Score:[/cyan] [bold]{score}%[/bold]\n\n"
                        f"[bold]Why this matches:[/bold]\n"
                        + "\n".join(f"  • {r}" for r in reasons)
                        + (
                            f"\n\n[dim]Description:[/dim]\n{job.get('description', '')[:500]}"
                            if job.get("description")
                            else ""
                        ),
                        title="[bold]Job Details[/bold]",
                        border_style="green",
                    )
                    console.print(detail_panel)
                else:
                    console.print("[red]Invalid number[/red]")
            except ValueError:
                console.print("[red]Invalid input[/red]")


def main():
    console.print(
        Panel.fit(
            "[bold cyan]Job Finder[/bold cyan]\n"
            "[dim]Find the most relevant jobs for your profile[/dim]",
            border_style="cyan",
        )
    )

    profile = build_or_load_profile()
    if not profile:
        console.print("[red]Profile is required to find jobs. Exiting.[/red]")
        sys.exit(1)

    config = load_config()

    if not check_serpapi_available():
        if Confirm.ask(
            "[yellow]SerpAPI key not configured.[/yellow] "
            "This enables Google Jobs results (free tier: 100 searches/month). "
            "Configure now?",
            default=False,
        ):
            key = Prompt.ask("Enter your SerpAPI key", password=False)
            if key.strip():
                config["serpapi_key"] = key.strip()
                save_config(config)
                console.print("[green]SerpAPI key saved![/green]")

    default_query = config.get("last_query", "")
    default_location = config.get("last_location", "")

    console.print("\n[bold]Search Parameters[/bold]")
    query = Prompt.ask(
        "Job search query",
        default=(
            profile.get("title")
            or profile.get("headline")
            or default_query
            or ""
        ),
    )

    location = Prompt.ask("Location (or leave blank for remote)", default=default_location or "")

    save_config({
        "last_query": query,
        "last_location": location,
    })

    profile["location"] = location

    jobs, source_counts = search_jobs(query, location)

    if jobs:
        ranked = rank_jobs(jobs, profile)
        display_results(ranked, source_counts)
    else:
        console.print(
            "[yellow]Could not fetch any job listings. "
            "Try running again with different search terms.[/yellow]"
        )

    console.print("\n[dim]Tip: Run again to search with different terms.[/dim]")


if __name__ == "__main__":
    main()
