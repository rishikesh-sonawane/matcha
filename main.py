#!/usr/bin/env python3
import argparse
import re
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from profile import build_or_load_profile
from typing import Any, Optional

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window
from rapidfuzz import fuzz
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from actions import is_job_saved, load_saved_jobs, save_job, unsave_job
from ai import ai_generate_queries, check_ai_available
from config import load_config, save_config
from matcher import compute_relevance, compute_relevance_ai
from scrapers.indeed import search_indeed_jobs
from scrapers.linkedin import search_linkedin_jobs
from scrapers.naukri import search_naukri_jobs
from scrapers.remoteok import search_remoteok_jobs
from scrapers.serpapi_jobs import check_serpapi_available, search_serpapi_jobs
from scrapers.web_search import search_web_for_jobs
from settings import load_settings

console = Console()


SCRAPER_DEFS = {
    "LinkedIn": search_linkedin_jobs,
    "Indeed": search_indeed_jobs,
    "Naukri": search_naukri_jobs,
    "RemoteOK": search_remoteok_jobs,
    "Web Search": search_web_for_jobs,
}


def configure_serpapi():
    if check_serpapi_available():
        return
    if not Confirm.ask(
        "[yellow]Configure SerpAPI for Google Jobs?[/yellow] (free tier: 100/mo)",
        default=False,
    ):
        return
    key = Prompt.ask("Enter your SerpAPI key", password=False)
    if key.strip():
        config = load_config()
        config["serpapi_key"] = key.strip()
        save_config(config)
        console.print("[green]SerpAPI key saved![/green]")


def configure_ai():
    if check_ai_available():
        return
    if not Confirm.ask(
        "[yellow]Configure AI matching?[/yellow] "
        "(enables profile enhancement, query expansion, job scoring)",
        default=False,
    ):
        return
    from ai import configure_ai as set_ai_key

    key = Prompt.ask("Enter your AI API key (or set $MINIMAX env var)", password=False)
    if key.strip():
        set_ai_key(key.strip())
        console.print("[green]AI key saved![/green]")


def run_scraper(
    name: str,
    scraper_func: Any,
    query: str,
    location: str,
    days: Optional[int] = None,
) -> tuple[str, list[dict[str, Any]]]:
    try:
        results = scraper_func(query, location, days=days)
        return name, results
    except Exception:
        return name, []


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\b(ii|iii|iv|sr?|jr)\b", "", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def deduplicate(
    jobs: list[dict[str, Any]],
    title_threshold: int = 82,
    company_threshold: int = 88,
) -> list[dict[str, Any]]:
    seen: list[tuple[str, str]] = []
    unique: list[dict[str, Any]] = []
    for j in jobs:
        norm_title = _normalize(j.get("title", ""))
        norm_company = _normalize(j.get("company", ""))
        is_duplicate = False
        for s_title, s_company in seen:
            title_sim = fuzz.token_sort_ratio(norm_title, s_title)
            company_sim = (
                fuzz.token_sort_ratio(norm_company, s_company)
                if not norm_company or not s_company
                else fuzz.token_set_ratio(norm_company, s_company)
            )
            if title_sim >= title_threshold and company_sim >= company_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            seen.append((norm_title, norm_company))
            unique.append(j)
    return unique


def search_jobs(
    queries: list[str],
    location: str,
    days: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if isinstance(queries, str):
        queries = [queries]

    scrapers = dict(SCRAPER_DEFS)
    if check_serpapi_available():
        scrapers["Google Jobs"] = search_serpapi_jobs

    all_jobs = []
    source_counts = {}
    pending = {name: True for name in scrapers}

    total_tasks = len(scrapers) * len(queries)

    with Live(console=console, refresh_per_second=4, transient=True) as live:

        def _status_table():
            t = Table(
                box=box.SIMPLE,
                show_header=False,
                show_edge=False,
                padding=(0, 2),
            )
            t.add_column("Status", width=2, no_wrap=True)
            t.add_column("Source", width=14, no_wrap=True)
            t.add_column("Results", width=8, justify="right")
            for name in sorted(scrapers):
                status = "..." if pending.get(name) else "OK"
                count = source_counts.get(name, 0)
                s = f"[green]{status}[/green]" if status == "OK" else f"[yellow]{status}[/yellow]"
                c = f"[green]{count}[/green]" if count > 0 else "[dim]0[/dim]"
                t.add_row(s, name, c)
            return t

        live.update(_status_table())

        with ThreadPoolExecutor(max_workers=min(total_tasks, 12)) as executor:
            futures = {}
            for name, func in scrapers.items():
                for q in queries:
                    f = executor.submit(run_scraper, f"{name}({q})", func, q, location, days)
                    futures[f] = name

            for future in as_completed(futures):
                name, jobs = future.result()
                source_name = name.split("(")[0]
                unique = deduplicate(jobs)
                source_counts[source_name] = source_counts.get(source_name, 0) + len(unique)
                pending[source_name] = False
                all_jobs.extend(unique)
                live.update(_status_table())
                time.sleep(0.05)

    return all_jobs, source_counts


RankedJob = tuple[float, dict[str, Any], list[str]]


def rank_jobs(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    use_ai: bool = False,
) -> list[RankedJob]:
    ranked: list[RankedJob] = []
    for job in jobs:
        relevance = compute_relevance(job, profile)
        ranked.append((relevance["score"], job, relevance["reasons"]))
    ranked.sort(key=lambda x: x[0], reverse=True)

    if use_ai:
        ai_top_n = min(15, len(ranked))
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[yellow]AI-scoring top candidates...", total=ai_top_n)
            with ThreadPoolExecutor(max_workers=min(ai_top_n, 8)) as ai_executor:
                ai_futures = {
                    ai_executor.submit(compute_relevance_ai, ranked[i][1], profile): i
                    for i in range(ai_top_n)
                }
                for f in as_completed(ai_futures):
                    i = ai_futures[f]
                    relevance = f.result()
                    if relevance:
                        ranked[i] = (relevance["score"], ranked[i][1], relevance["reasons"])
                    progress.update(task, advance=1)
        ranked.sort(key=lambda x: x[0], reverse=True)

    return ranked


def build_results_table(
    ranked: list[RankedJob],
    page: int,
    page_size: int,
    total_pages: int,
    ai_enabled: bool,
    saved_ids: dict[str, Any],
    highlight: Optional[int] = None,
) -> Table:
    start = page * page_size
    end = min(start + page_size, len(ranked))

    title = f"[bold]Matching Jobs[/bold] [dim](page {page + 1}/{total_pages})[/dim]"
    if ai_enabled:
        title += " [yellow](AI)[/yellow]"

    table = Table(
        title=title,
        box=box.SIMPLE,
        header_style="bold cyan",
        show_edge=False,
    )
    table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("Title", style="bold", width=22, overflow="ellipsis")
    table.add_column("Company", width=14, overflow="ellipsis")
    table.add_column("Source", width=8, no_wrap=True)
    table.add_column("Match", justify="right", width=6, no_wrap=True)

    for i, (score, job, reasons) in enumerate(ranked[start:end], start + 1):
        score_color = "green" if score >= 60 else "yellow" if score >= 25 else "red"
        url = job.get("url", "")
        saved_mark = " [yellow]★[/yellow]" if url and is_job_saved(url, saved_ids) else ""
        row_style = (
            "reverse bold" if highlight is not None and (i - 1) == (start + highlight) else None
        )
        table.add_row(
            str(i),
            job.get("title", "N/A") + saved_mark,
            job.get("company", "N/A"),
            job.get("source", "N/A"),
            f"[{score_color}]{score}%[/{score_color}]",
            style=row_style,
        )

    return table


def show_job_detail(job: dict[str, Any], score: float, reasons: list[str]) -> None:
    console.print()
    console.print(
        Panel(
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
    )


def prompt_loop(
    ranked: list[RankedJob],
    source_counts: dict[str, int],
    ai_enabled: bool,
) -> Optional[str]:
    ranked = [(s, j, r) for s, j, r in ranked if s > 0]
    if not ranked:
        console.print("[yellow]No jobs matched your profile sufficiently.[/yellow]")
        return

    summary_parts = [
        f"[cyan]{count}[/] from [bold]{name}[/]"
        for name, count in sorted(source_counts.items())
        if count > 0
    ]
    ai_tag = " [bold yellow](AI)[/bold yellow]" if ai_enabled else ""
    console.print(f"\n[bold]Found {len(ranked)} total jobs[/bold]{ai_tag}")
    console.print("  " + " | ".join(summary_parts))

    page_size = 10
    total_pages = max(1, (len(ranked) + page_size - 1) // page_size)
    saved_ids = load_saved_jobs()

    class State:
        page: int = 0
        selected: int = 0
        mode: str = "list"
        detail_idx: int = 0
        re_run: bool = False

    st = State()

    help_text = (
        "[dim]\u2191\u2193[/dim] navigate  [dim]Enter[/dim] detail  "
        "[dim]s[/dim] save/unsave  [dim]o[/dim] open  "
        "[dim]n[/dim]/[dim]p[/dim] page  [dim]l[/dim] saved  [dim]r[/dim] re-run  [dim]q[/dim] quit"
    )
    saved_help = "[dim]Press any key to go back...[/dim]"
    detail_help = (
        "[dim]Enter[/dim] back  [dim]o[/dim] open  [dim]s[/dim] save/unsave  [dim]q[/dim] quit"
    )

    def _do_save(job):
        url = job.get("url", "")
        if not url:
            return
        if is_job_saved(url, saved_ids):
            unsave_job(url)
            saved_ids.pop(url, None)
        else:
            save_job(job)
            saved_ids[url] = {
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "url": url,
                "source": job.get("source", ""),
            }

    def _render_content():
        with console.capture() as cap:
            if st.mode == "detail":
                score, job, reasons = ranked[st.detail_idx]
                show_job_detail(job, score, reasons)
            elif st.mode == "saved":
                if not saved_ids:
                    console.print("[dim]No saved jobs yet.[/dim]")
                else:
                    t = Table(
                        box=box.SIMPLE,
                        title="[bold]Saved Jobs[/bold]",
                        show_edge=False,
                    )
                    t.add_column("Title", width=30, overflow="ellipsis")
                    t.add_column("Company", width=16, overflow="ellipsis")
                    t.add_column("Source", width=10)
                    for entry in saved_ids.values():
                        t.add_row(
                            entry.get("title", ""),
                            entry.get("company", ""),
                            entry.get("source", ""),
                        )
                    console.print(t)
            else:
                console.print(
                    build_results_table(
                        ranked,
                        st.page,
                        page_size,
                        total_pages,
                        ai_enabled,
                        saved_ids,
                        highlight=st.selected,
                    )
                )
        return cap.get()

    def _render_help():
        with console.capture() as cap:
            if st.mode == "detail":
                console.print(detail_help)
            elif st.mode == "saved":
                console.print(saved_help)
            else:
                console.print(help_text)
        return cap.get()

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        if st.mode != "list":
            return
        if st.selected > 0:
            st.selected -= 1
        elif st.page > 0:
            st.page -= 1
            pc = min(page_size, len(ranked) - st.page * page_size)
            st.selected = pc - 1
        event.app.invalidate()

    @kb.add("down")
    def _down(event):
        if st.mode != "list":
            return
        ps = st.page * page_size
        pe = min(ps + page_size, len(ranked))
        if st.selected < pe - ps - 1:
            st.selected += 1
        elif st.page + 1 < total_pages:
            st.page += 1
            st.selected = 0
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event):
        if st.mode in ("detail", "saved"):
            st.mode = "list"
        else:
            idx = st.page * page_size + st.selected
            if 0 <= idx < len(ranked):
                st.mode = "detail"
                st.detail_idx = idx
        event.app.invalidate()

    @kb.add("q")
    @kb.add("Q")
    def _quit(event):
        event.app.exit()

    @kb.add("n")
    @kb.add("N")
    def _next(event):
        if st.mode == "list" and st.page + 1 < total_pages:
            st.page += 1
            st.selected = 0
            event.app.invalidate()

    @kb.add("p")
    @kb.add("P")
    def _prev(event):
        if st.mode == "list" and st.page > 0:
            st.page -= 1
            st.selected = 0
            event.app.invalidate()

    @kb.add("s")
    @kb.add("S")
    def _save(event):
        if st.mode == "list":
            idx = st.page * page_size + st.selected
        elif st.mode == "detail":
            idx = st.detail_idx
        else:
            return
        if 0 <= idx < len(ranked):
            _do_save(ranked[idx][1])
        event.app.invalidate()

    @kb.add("o")
    @kb.add("O")
    def _open(event):
        idx = -1
        if st.mode == "list":
            idx = st.page * page_size + st.selected
        elif st.mode == "detail":
            idx = st.detail_idx
        if 0 <= idx < len(ranked):
            url = ranked[idx][1].get("url", "")
            if url:
                webbrowser.open(url)

    @kb.add("l")
    @kb.add("L")
    def _saved(event):
        st.mode = "saved"
        event.app.invalidate()

    @kb.add("r")
    @kb.add("R")
    def _rerun(event):
        st.re_run = True
        event.app.exit()

    app = Application(
        layout=Layout(
            HSplit(
                [
                    Window(content=FormattedTextControl(lambda: ANSI(_render_content()))),
                    Window(
                        height=1,
                        content=FormattedTextControl(lambda: ANSI(_render_help())),
                    ),
                ]
            )
        ),
        key_bindings=kb,
        full_screen=True,
        mouse_support=False,
    )

    try:
        app.run()
    except KeyboardInterrupt:
        pass

    if st.re_run:
        return "re_run"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Job Finder — multi-source job search with relevance ranking"
    )
    parser.add_argument("--configure", action="store_true", help="Configure API keys (SerpAPI, AI)")
    parser.add_argument(
        "--new-profile", "-n", action="store_true", help="Re-enter profile from scratch"
    )
    parser.add_argument(
        "--non-interactive", "-b", action="store_true", help="Skip prompts (requires YAML config)"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config file")
    args = parser.parse_args()

    if args.configure:
        configure_serpapi()
        configure_ai()
        console.print(
            "[green]Configuration complete![/green] Run [bold]python3 main.py[/bold] to search."
        )
        return

    settings = load_settings(config_path=args.config)

    console.print(
        Panel.fit(
            "[bold cyan]Job Finder[/bold cyan]\n"
            "[dim]Multi-source job search with relevance ranking[/dim]",
            border_style="cyan",
        )
    )

    profile = build_or_load_profile(force_new=args.new_profile)
    if not profile:
        console.print("[red]Profile is required. Run with --new-profile to set one up.[/red]")
        sys.exit(1)

    use_ai = check_ai_available() and settings["ai"]["enabled"]

    config = load_config()
    default_query = (
        config.get("last_query")
        or settings["search"].get("query")
        or profile.get("title")
        or profile.get("headline")
        or ""
    )
    default_location = config.get("last_location") or settings["search"].get("location") or ""
    default_days = config.get("last_days") or settings["search"].get("days", 7)

    if args.non_interactive:
        query = default_query
        location = default_location
        days = default_days
        if not query:
            console.print(
                "[red]No search query configured. Set it in YAML config or use interactive mode.[/red]"
            )
            sys.exit(1)
    else:
        console.print()
        query = Prompt.ask("Job search query", default=default_query)
        location = Prompt.ask("Location (or blank for remote)", default=default_location)
        days_str = Prompt.ask("Show jobs posted within how many days?", default=str(default_days))
        try:
            days = max(1, int(days_str))
        except ValueError:
            days = None

    save_config({"last_query": query, "last_location": location, "last_days": days})
    profile["location"] = location

    queries = [query]
    if use_ai:
        ai_queries = ai_generate_queries(profile)
        if ai_queries:
            extra = [q for q in ai_queries if q.lower() != query.lower()]
            if extra:
                queries.extend(extra)
                console.print(f"[dim]AI queries: {', '.join(queries)}[/dim]")

    jobs, source_counts = search_jobs(queries, location, days=days)
    if not jobs:
        console.print("[yellow]No jobs found. Try different search terms.[/yellow]")
        return

    ranked = rank_jobs(jobs, profile, use_ai=use_ai)
    result = prompt_loop(ranked, source_counts, ai_enabled=use_ai)

    if result == "re_run":
        console.print()
        main()


if __name__ == "__main__":
    main()
