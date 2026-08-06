#!/usr/bin/env python3
import argparse
import logging
import logging.handlers
import re
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from pathlib import Path
from typing import Any

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

from matcha.actions import is_job_saved, load_saved_jobs, save_job, unsave_job
from matcha.ai import (
    ai_generate_queries,
    budget_used,
    check_ai_available,
    reset_budget,
)
from matcha.config import load_config, save_config
from matcha.filters import apply_filters, build_filter_summary, provenance_tags
from matcha.matcher import (
    ai_eligible,
    compute_relevance,
    compute_relevance_ai,
    detect_flatline,
    normalize_scores,
)
from matcha.models import ScraperResult
from matcha.normalization import normalize_jobs
from matcha.profile import build_or_load_profile
from matcha.settings import load_settings
from matcha.sources.indeed import search_indeed_jobs
from matcha.sources.linkedin import search_linkedin_jobs
from matcha.sources.naukri import search_naukri_jobs
from matcha.sources.remoteok import search_remoteok_jobs
from matcha.sources.serpapi_jobs import check_serpapi_available, search_serpapi_jobs
from matcha.sources.web_search import search_web_for_jobs

console = Console()

_log_dir = Path.home() / ".matcha" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            Path.home() / ".matcha" / "logs" / "matcha.log",
            maxBytes=5_000_000,
            backupCount=3,
        ),
    ],
)
for _lib in ("primp", "httpx", "ddgs", "urllib3"):
    logging.getLogger(_lib).setLevel(logging.WARNING)
logger = logging.getLogger("matcha")


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
    """AI setup wizard (Phase 5, strategy §10.2): pick a provider preset.

    Presets (Groq / Kilo Gateway / OpenRouter / OpenAI-compatible / local)
    fill in the URL + model defaults; the wizard only asks for the API key
    (not needed for local endpoints) and optional overrides. The key goes to
    the normal secret store (keyring/fernet), never plaintext.
    """
    if check_ai_available():
        return
    if not Confirm.ask(
        "[yellow]Configure AI matching?[/yellow] "
        "(enables profile enhancement, query expansion, job scoring)",
        default=False,
    ):
        return
    from matcha.ai import PROVIDERS, configure_provider

    label_to_provider = {p["label"]: k for k, p in PROVIDERS.items()}
    choices = list(label_to_provider)
    selection = Prompt.ask("Select an AI provider", choices=choices, default=choices[1])
    provider = label_to_provider[selection]

    key = ""
    if PROVIDERS[provider].get("requires_key", True):
        key = Prompt.ask("Enter your API key (or set $AI_API_KEY env var)", password=True)
    url = Prompt.ask("API URL override (blank = provider default)", default="")
    model = Prompt.ask("Model override (blank = provider default)", default="")
    configure_provider(provider, key.strip(), url=url.strip(), model=model.strip())
    console.print(f"[green]AI configuration saved ({selection})![/green]")


def configure_opencli():
    """One-time consent flow for the OpenCLI browser bridge (strategy §6.3).

    Gated on ``opencli_status().ready``: never ask when the bridge is down.
    Opting in writes ``linkedin_consent`` / ``indeed_consent`` to config.json;
    both default to False, so OpenCLI is only ever used after an explicit yes.
    """
    from matcha.sources.backends.opencli import OPENCLI_EXTENSION_URL, opencli_status

    st = opencli_status()
    if not st.installed:
        console.print(
            "[yellow]OpenCLI is not installed.[/yellow] It lets Matcha search "
            "LinkedIn/Indeed through your logged-in Chrome for far richer results.\n"
            f"  npm install -g @jackwener/opencli\n"
            f"Then enable the extension: {OPENCLI_EXTENSION_URL}"
        )
        return
    if st.broken:
        console.print(
            "[yellow]OpenCLI is installed but cannot execute[/yellow] "
            "(broken node environment). Reinstall:\n  npm install -g @jackwener/opencli"
        )
        return
    if not st.extension_connected:
        console.print(
            "[yellow]OpenCLI is installed but its browser bridge is not connected.[/yellow]\n"
            "  1. Keep Chrome open with the OpenCLI extension enabled\n"
            f"  2. Install/enable the extension: {OPENCLI_EXTENSION_URL}\n"
            "  3. Run `matcha --configure` again"
        )
        return

    config = load_config()
    for label, key in (("LinkedIn", "linkedin_consent"), ("Indeed", "indeed_consent")):
        if Confirm.ask(
            f"[yellow]Use your logged-in Chrome for {label} searches?[/yellow] "
            "(OpenCLI backend: salary, listed dates, stable URLs)",
            default=False,
        ):
            config[key] = True
    save_config(config)
    console.print(
        "[green]OpenCLI consent saved![/green] (run `matcha doctor` to see live backends)"
    )


def run_scraper(
    name: str,
    scraper_func: Any,
    query: str,
    location: str,
    days: int | None = None,
    max_pages: int = 1,
    **kwargs: Any,
) -> tuple[str, ScraperResult]:
    try:
        result = scraper_func(query, location, days=days, max_pages=max_pages, **kwargs)
        if isinstance(result, ScraperResult):
            return name, result
        return name, ScraperResult(jobs=result, source=name.split("(")[0])
    except Exception as e:
        logger.error("Scraper %s crashed: %s", name, e, exc_info=True)
        return name, ScraperResult(errors=[str(e)], source=name.split("(")[0])


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
            if norm_company and s_company:
                company_sim = fuzz.token_set_ratio(norm_company, s_company)
            else:
                company_sim = (
                    fuzz.token_sort_ratio(norm_company, s_company)
                    if norm_company or s_company
                    else 100
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
    days: int | None = None,
    max_pages: int = 1,
    indeed_domain: str = "in.indeed.com",
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, list[str]]]:
    if isinstance(queries, str):
        queries = [queries]

    queries = [q for q in (queries or []) if q]
    if not queries:
        return [], {}, {}

    scrapers = dict(SCRAPER_DEFS)
    if check_serpapi_available():
        scrapers["Google Jobs"] = search_serpapi_jobs

    all_jobs = []
    source_counts: dict[str, int] = {}
    source_errors: dict[str, list[str]] = {}
    pending = {name: True for name in scrapers}

    total_tasks = len(scrapers) * len(queries)

    scraper_kwargs: dict[str, dict[str, Any]] = {}
    if "Indeed" in scrapers:
        scraper_kwargs["Indeed"] = {"domain": indeed_domain}

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
                status = (
                    "..."
                    if pending.get(name)
                    else "OK"
                    if source_errors.get(name) is None
                    else "ERR"
                )
                count = source_counts.get(name, 0)
                s = (
                    f"[green]{status}[/green]"
                    if status == "OK"
                    else f"[yellow]{status}[/yellow]"
                    if status == "..."
                    else f"[red]{status}[/red]"
                )
                c = (
                    f"[green]{count}[/green]"
                    if count > 0
                    else (
                        f"[red]{len(source_errors.get(name, []))} err[/red]"
                        if source_errors.get(name)
                        else "[dim]0[/dim]"
                    )
                )
                t.add_row(s, name, c)
            return t

        live.update(_status_table())

        executor = ThreadPoolExecutor(max_workers=min(total_tasks, 12))
        try:
            futures = {}
            for name, func in scrapers.items():
                extra = scraper_kwargs.get(name, {})
                for q in queries:
                    f = executor.submit(
                        run_scraper, f"{name}({q})", func, q, location, days, max_pages, **extra
                    )
                    futures[f] = name

            _last_state: tuple[bytes, ...] | None = None
            try:
                for future in as_completed(futures, timeout=45):
                    source_name = futures[future]
                    _, result = future.result()
                    pending[source_name] = False
                    if result.errors:
                        source_errors.setdefault(source_name, []).extend(result.errors)
                    # Provenance is data (strategy §6.2): stamp the result-level
                    # quality/backend onto every row so ranker + TUI tags work for
                    # all sources (only Naukri/enrichment set per-row flags today).
                    for job in result.jobs:
                        job.setdefault("data_quality", result.data_quality)
                        job.setdefault("backend", result.backend)
                    unique = deduplicate(result.jobs)
                    source_counts[source_name] = source_counts.get(source_name, 0) + len(unique)
                    all_jobs.extend(unique)
                    _state = (
                        str(pending).encode(),
                        str(source_counts).encode(),
                        str(source_errors).encode(),
                    )
                    if _state != _last_state:
                        live.update(_status_table())
                        _last_state = _state
                    time.sleep(0.05)
            except TimeoutError:
                logger.warning("Scraper batch timed out after 45s, returning partial results")
                live.update(_status_table())
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    all_jobs = deduplicate(all_jobs)
    return all_jobs, source_counts, source_errors


RankedJob = tuple[float, dict[str, Any], list[str]]


def rank_jobs(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    use_ai: bool = False,
    ai_top_n: int = 30,
    ai_timeout: int = 60,
    normalize_flatline: bool = False,
) -> list[RankedJob]:
    ranked: list[RankedJob] = []
    for job in jobs:
        relevance = compute_relevance(job, profile)
        ranked.append((relevance["score"], job, relevance["reasons"]))
    ranked.sort(key=lambda x: x[0], reverse=True)

    # Phase 4 (§9.3): the AI pass runs only on enriched candidates — the prompt
    # weights finally have real description/location inputs, never snippet noise.
    if use_ai:
        ai_idx = [i for i, (_, job, _) in enumerate(ranked) if ai_eligible(job)]
        ai_idx = ai_idx[: min(len(ai_idx), ai_top_n)]
        if ai_idx:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("[yellow]AI-scoring top candidates...", total=len(ai_idx))
                with ThreadPoolExecutor(max_workers=min(len(ai_idx), 8)) as ai_executor:
                    ai_futures = {
                        ai_executor.submit(
                            compute_relevance_ai, ranked[i][1], profile, ai_timeout=ai_timeout
                        ): i
                        for i in ai_idx
                    }
                    for f in as_completed(ai_futures):
                        i = ai_futures[f]
                        relevance = f.result()
                        if relevance:
                            ranked[i] = (relevance["score"], ranked[i][1], relevance["reasons"])
                        progress.update(task, advance=1)
            ranked.sort(key=lambda x: x[0], reverse=True)

    # Phase 4 (§9.4): calibration guard on the FINAL scores (post-AI, so the
    # presented distribution is what we judge). Homogeneous scores mean the
    # heuristic couldn't separate signal; flag it and optionally spread them.
    if detect_flatline([r[0] for r in ranked]):
        logger.warning(
            "Score distribution is flat (top-decile spread < %.1f) — results are "
            "homogeneous; enriched jobs should outrank snippet-guesses",
            5.0,
        )
        if normalize_flatline:
            scores = normalize_scores([r[0] for r in ranked])
            ranked = [(scores[i], ranked[i][1], ranked[i][2]) for i in range(len(ranked))]

    return ranked


def build_results_table(
    ranked: list[RankedJob],
    page: int,
    page_size: int,
    total_pages: int,
    ai_enabled: bool,
    saved_ids: dict[str, Any],
    highlight: int | None = None,
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
        if score >= 60:
            score_color = "green"
        elif score >= 25:
            score_color = "yellow"
        elif score >= 5:
            score_color = "dim"
        else:
            score_color = "red"
        url = job.get("url", "")
        saved_mark = " [yellow]\u2605[/yellow]" if url and is_job_saved(url, saved_ids) else ""
        # Provenance tags (strategy §9.6): [full]/[partial]/[snippet] + [age?]/[salary?].
        tags = "".join(f"[dim][{t}][/dim]" for t in provenance_tags(job))
        row_style = (
            "reverse bold" if highlight is not None and (i - 1) == (start + highlight) else None
        )
        table.add_row(
            str(i),
            job.get("title", "N/A") + saved_mark,
            job.get("company", "N/A"),
            job.get("source", "N/A"),
            f"[{score_color}]{score}%[/{score_color}]{tags}",
            style=row_style,
        )

    return table


def show_job_detail(job: dict[str, Any], score: float, reasons: list[str]) -> None:
    lines = [f"[bold]{job.get('title', 'N/A')}[/bold]"]
    lines.append(f"[cyan]Company:[/cyan] {job.get('company', 'N/A')}")
    if job.get("salary"):
        lines.append(f"[cyan]Salary:[/cyan] {job['salary']}")
    if job.get("workplace_type"):
        lines.append(f"[cyan]Workplace:[/cyan] {job['workplace_type']}")
    if job.get("listed"):
        lines.append(f"[cyan]Posted:[/cyan] {job['listed']}")
    if job.get("applicants"):
        lines.append(f"[cyan]Applicants:[/cyan] {job['applicants']}")
    lines.append(f"[cyan]Location:[/cyan] {job.get('location', 'N/A')}")
    lines.append(f"[cyan]Source:[/cyan] {job.get('source', 'N/A')}")
    url = job.get("apply_url") or job.get("url", "")
    label = "Apply URL" if job.get("apply_url") else "URL"
    lines.append(f"[cyan]{label}:[/cyan] {url}")
    lines.append(f"[cyan]Match Score:[/cyan] [bold]{score}%[/bold]")
    lines.append("")
    lines.append("[bold]Why this matches:[/bold]")
    lines.extend(f"  \u2022 {r}" for r in reasons)
    if job.get("description"):
        lines.append(f"\n[dim]Description:[/dim]\n{job['description'][:800]}")
    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Job Details[/bold]",
            border_style="green",
        )
    )


def _dedup_queries(queries: list[str]) -> list[str]:
    if len(queries) < 2:
        return queries
    unique: list[str] = []
    for q in queries:
        is_dup = False
        q_norm = _normalize(q)
        for existing in unique:
            if fuzz.token_sort_ratio(q_norm, _normalize(existing)) > 85:
                is_dup = True
                break
        if not is_dup:
            unique.append(q)
    return unique


def _validate_queries(queries: list[str]) -> list[str]:
    from matcha.sources.constants import STOP_WORDS

    valid: list[str] = []
    for q in queries:
        tokens = [t for t in q.lower().split() if t not in STOP_WORDS and len(t) > 1]
        if len(tokens) >= 2:
            valid.append(q)
    return valid


def prompt_loop(
    ranked: list[RankedJob],
    source_counts: dict[str, int],
    source_errors: dict[str, list[str]],
    ai_enabled: bool,
    filter_summary: str = "",
) -> str | None:
    if not ranked:
        console.print("[yellow]No jobs found. Try different search terms.[/yellow]")
        return

    summary_parts = [
        f"[cyan]{count}[/] from [bold]{name}[/]"
        for name, count in sorted(source_counts.items())
        if count > 0
    ]
    error_parts = [
        f"[red]{name}: {len(errs)} error(s)[/red]"
        for name, errs in sorted(source_errors.items())
        if errs
    ]
    ai_tag = " [bold yellow](AI)[/bold yellow]" if ai_enabled else ""
    console.print(f"\n[bold]Found {len(ranked)} total jobs[/bold]{ai_tag}")
    console.print("  " + " | ".join(summary_parts))
    if filter_summary:
        console.print(f"  [dim]Filtered: {len(ranked)} kept ({filter_summary})[/dim]")
    if error_parts:
        console.print("  [bold]Errors:[/bold] " + " | ".join(error_parts))

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
            job = ranked[idx][1]
            # Enriched jobs carry an apply_url (strategy §8) — prefer it.
            url = job.get("apply_url") or job.get("url", "")
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


def run() -> None:
    parser = argparse.ArgumentParser(
        description="Matcha \u2014 multi-source job search with relevance ranking"
    )
    subparsers = parser.add_subparsers(dest="command")
    doctor_parser = subparsers.add_parser("doctor", help="Check job-source health")
    doctor_parser.add_argument("--json", action="store_true", help="Emit the report as JSON")
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Configure API keys (SerpAPI, AI provider) + OpenCLI consent",
    )
    parser.add_argument(
        "--new-profile", "-n", action="store_true", help="Re-enter profile from scratch"
    )
    parser.add_argument(
        "--non-interactive", "-b", action="store_true", help="Skip prompts (requires YAML config)"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config file")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only jobs posted within N days (central filter; overrides settings)",
    )
    args = parser.parse_args()

    if args.command == "doctor":
        from matcha.doctor import check_all, format_report, report_to_json

        results = check_all(config=load_settings(config_path=args.config))
        if args.json:
            print(report_to_json(results))
        else:
            console.print(format_report(results))
        return

    if args.configure:
        configure_serpapi()
        configure_ai()
        configure_opencli()
        console.print("[green]Configuration complete![/green] Run [bold]matcha[/bold] to search.")
        return

    settings = load_settings(config_path=args.config)

    console.print(
        Panel.fit(
            "[bold cyan]Matcha[/bold cyan]\n"
            "[dim]Multi-source job search with relevance ranking[/dim]",
            border_style="cyan",
        )
    )

    while True:
        profile = build_or_load_profile(force_new=args.new_profile)
        if not profile:
            console.print("[red]Profile is required. Run with --new-profile to set one up.[/red]")
            sys.exit(1)

        use_ai = check_ai_available() and settings["ai"]["enabled"]

        # Phase 5 (§10.2): fresh AI budget per run (queries + scoring share it).
        reset_budget(max_calls=settings.get("ai", {}).get("max_calls", 60))

        config = load_config()
        default_query = (
            profile.get("title")
            or profile.get("headline")
            or settings["search"].get("query")
            or config.get("last_query")
            or ""
        )
        default_location = (
            profile.get("location")
            or settings["search"].get("location")
            or config.get("last_location")
            or ""
        )
        last_days = config.get("last_days")
        default_days = last_days if last_days is not None else settings["search"].get("days", 7)

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
            days_str = Prompt.ask(
                "Show jobs posted within how many days?", default=str(default_days)
            )
            try:
                days = max(0, int(days_str))
            except ValueError:
                days = None

        if args.days is not None:
            # --days 0 = today only (strategy §7.1); don't let falsy-0 be ignored.
            days = max(0, int(args.days))

        save_config({"last_query": query, "last_location": location, "last_days": days})
        profile["location"] = location

        queries = [query]
        if use_ai:
            console.print("[yellow]Generating AI-powered search queries...[/yellow]")
            ai_queries = ai_generate_queries(profile)
            if ai_queries:
                extra = [q for q in ai_queries if q.lower() != query.lower()]
                if extra:
                    extra = _dedup_queries(extra)
                    extra = _validate_queries(extra)
                    queries.extend(extra)
                    console.print(f"[dim]AI queries: {', '.join(queries)}[/dim]")

        max_pages = settings.get("search", {}).get("max_pages", 2)
        indeed_domain = settings.get("scrapers", {}).get("indeed_domain", "in.indeed.com")
        jobs, source_counts, source_errors = search_jobs(
            queries, location, days=days, max_pages=max_pages, indeed_domain=indeed_domain
        )
        if not jobs:
            console.print("[yellow]No jobs found. Try different search terms.[/yellow]")
            result = Prompt.ask("Search again?", default="y")
            if result.lower() in ("y", "yes"):
                continue
            break

        # Phase 2 (strategy §7): normalize → central filter pipeline. The age
        # filter is the FINAL authority on job freshness — scrapers pass the
        # same window only to fetch less, never to bypass it.
        filters_cfg = dict(settings.get("filters", {}))
        if days is not None:
            filters_cfg["days"] = days
        with console.status("[yellow]Filtering results...[/yellow]"):
            jobs = normalize_jobs(jobs)
            jobs, filter_reports = apply_filters(jobs, profile, filters_cfg)
        filter_summary = build_filter_summary(filter_reports)
        if not jobs:
            console.print("[yellow]No jobs survived the filters.[/yellow]")
            if filter_summary:
                console.print(f"  [dim]Dropped: {filter_summary}[/dim]")
            result = Prompt.ask("Search again?", default="y")
            if result.lower() in ("y", "yes"):
                continue
            break

        ai_top_n = settings.get("ai", {}).get("top_n", 30)
        ai_timeout = settings.get("ai", {}).get("timeout", 60)
        normalize_flatline = settings.get("ranking", {}).get("normalize_scores", False)
        ranked = rank_jobs(
            jobs,
            profile,
            use_ai=use_ai,
            ai_top_n=ai_top_n,
            ai_timeout=ai_timeout,
            normalize_flatline=normalize_flatline,
        )

        # Phase 1 part 3 (strategy §7 step 7 / §8): enrich the top N with real
        # posting details (OpenCLI job-detail, Jina fallback). Silently skips
        # when not consented or the browser bridge is down.
        enrich_cfg = settings.get("enrichment", {})
        if enrich_cfg.get("enabled", True) and ranked:
            from matcha.sources.enrichment import enrich_top_n

            with console.status("[yellow]Enriching top jobs with full details...[/yellow]"):
                enriched, ranked = enrich_top_n(
                    ranked,
                    top_n=int(enrich_cfg.get("top_n", 30)),
                    max_workers=int(enrich_cfg.get("max_workers", 5)),
                    timeout=int(enrich_cfg.get("timeout", 30)),
                    config=config,
                )
            if enriched:
                console.print(f"[dim]Enriched [cyan]{enriched}[/cyan] top jobs with details[/dim]")

        # Phase 5 (§10.2): surface the budget guard outcome in the run summary.
        ai_calls = budget_used()
        if use_ai and ai_calls:
            max_calls = settings.get("ai", {}).get("max_calls", 60)
            remaining = max(0, max_calls - ai_calls)
            console.print(
                f"[dim]AI budget: {ai_calls}/{max_calls} calls used ({remaining} left)[/dim]"
            )
        result = prompt_loop(
            ranked,
            source_counts,
            source_errors,
            ai_enabled=use_ai,
            filter_summary=filter_summary,
        )

        if result != "re_run":
            break

        args.new_profile = False


def main() -> None:
    try:
        run()
    except Exception:
        logger.exception("Unhandled exception in main")
        console.print("[red]An unexpected error occurred. Check logs for details.[/red]")
        sys.exit(1)
    # F-05: sys.exit (was os._exit) so SQLite WAL commits flush and atexit
    # hooks run. ddgs worker threads are daemons and never block exit.
    sys.exit(0)


if __name__ == "__main__":
    main()
