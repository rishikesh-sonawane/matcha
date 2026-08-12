#!/usr/bin/env python3
import argparse
import json
import logging
import logging.handlers
import re
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
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

from matcha.actions import is_job_saved, job_entry, load_saved_jobs, save_job, unsave_job
from matcha.ai import (
    ai_generate_queries,
    ai_verdict,
    budget_used,
    check_ai_available,
    reset_budget,
)
from matcha.config import load_config, load_profile, save_config, save_profile
from matcha.filters import apply_filters, build_filter_summary, filter_notes, provenance_tags
from matcha.matcher import (
    ai_eligible,
    compute_relevance,
    compute_relevance_ai,
    detect_flatline,
    normalize_scores,
)
from matcha.models import ScraperResult
from matcha.normalization import normalize_jobs, search_location
from matcha.profile import build_or_load_profile
from matcha.settings import (
    DDGS_WEB_SEARCH_CAP,
    DEFAULT_BATCH_TIMEOUT,
    DEFAULT_QUERY_CAPS,
    load_settings,
)
from matcha.sources.breaker import is_open as breaker_is_open
from matcha.sources.breaker import record_failure as breaker_record_failure
from matcha.sources.breaker import record_success as breaker_record_success
from matcha.sources.indeed import search_indeed_jobs
from matcha.sources.linkedin import search_linkedin_jobs
from matcha.sources.naukri import search_naukri_jobs
from matcha.sources.remoteok import search_remoteok_jobs
from matcha.sources.serpapi_jobs import check_serpapi_available, search_serpapi_jobs
from matcha.sources.web_search import search_web_for_jobs
from matcha.track import mark_seen, partition_new
from matcha.track import stats as track_stats

console = Console()
_err_console = Console(stderr=True)  # status notes that must not corrupt piped JSON


class _NullLive:
    """No-op stand-in for rich ``Live`` when running headless (quiet mode).

    `matcha search --json` must not corrupt stdout with progress frames.
    """

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None


class _NullProgress:
    """No-op stand-in for rich ``Progress`` when running headless."""

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def add_task(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None


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

#: Display name -> circuit-breaker state key (strategy §6.7).
_BREAKER_KEYS = {
    "LinkedIn": "linkedin",
    "Indeed": "indeed",
    "Naukri": "naukri",
    "RemoteOK": "remoteok",
    "Web Search": "web_search",
    "Google Jobs": "serpapi",
    "RSS": "rss",
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
        key = Prompt.ask("Enter your API key (or set the $MINIMAX env var)", password=True)
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
    quiet: bool = False,
    extra_scrapers: dict[str, Any] | None = None,
    extra_scraper_kwargs: dict[str, dict[str, Any]] | None = None,
    query_caps: dict[str, int] | None = None,
    batch_timeout: int = DEFAULT_BATCH_TIMEOUT,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, list[str]]]:
    if isinstance(queries, str):
        queries = [queries]

    queries = [q for q in (queries or []) if q]
    if not queries:
        return [], {}, {}

    # Session 27: sources accept ONE location string. A multi-city preference
    # ("Pune, Bengaluru, Hyderabad") sent verbatim makes LinkedIn/Indeed
    # return almost nothing — derive a source-level location (country-wide
    # "India" for an all-Indian multi-city preference) and let the central
    # location FILTER keep exactly the preferred cities + remote.
    source_location = search_location(location)

    scrapers = dict(SCRAPER_DEFS)
    if extra_scrapers:
        scrapers.update(extra_scrapers)
    if check_serpapi_available():
        scrapers["Google Jobs"] = search_serpapi_jobs

    all_jobs = []
    source_counts: dict[str, int] = {}
    source_errors: dict[str, list[str]] = {}
    pending = {name: True for name in scrapers}

    # Phase 7 (strategy §6.7): skip sources whose circuit is open (>=3
    # consecutive failures) with a visible note; the doctor reports the state.
    breaker_keys = {name: _BREAKER_KEYS.get(name) for name in scrapers}
    for name, key in breaker_keys.items():
        if key and breaker_is_open(key):
            logger.warning("Skipping %s: circuit open (cooldown)", name)
            pending[name] = False
            source_errors.setdefault(name, []).append(
                "circuit open (≥3 consecutive failures) — skipped until cooldown ends"
            )
    scrapers = {n: f for n, f in scrapers.items() if pending[n]}

    total_tasks = len(scrapers) * len(queries)

    scraper_kwargs: dict[str, dict[str, Any]] = dict(extra_scraper_kwargs or {})
    if "Indeed" in scrapers:
        scraper_kwargs["Indeed"] = {"domain": indeed_domain}

    live_ctx: Any = (
        Live(console=console, refresh_per_second=4, transient=True) if not quiet else _NullLive()
    )
    with live_ctx as live:

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
                qs = queries
                if query_caps:
                    cap = query_caps.get(name)
                    if cap is not None and cap < len(qs):
                        qs = queries[:cap]
                for qi, q in enumerate(qs):
                    per_q = dict(extra)
                    if name == "Indeed":
                        # Session 21: only the primary query pays for the
                        # job-detail title-recovery pass (bounded, ~8 calls);
                        # variant queries reuse the same US-index rows.
                        per_q["recover_titles"] = qi == 0
                    f = executor.submit(
                        run_scraper,
                        f"{name}({q})",
                        func,
                        q,
                        source_location,
                        days,
                        max_pages,
                        **per_q,
                    )
                    futures[f] = name

            _last_state: tuple[bytes, ...] | None = None
            try:
                for future in as_completed(futures, timeout=batch_timeout):
                    source_name = futures[future]
                    _, result = future.result()
                    pending[source_name] = False
                    key = breaker_keys.get(source_name)
                    if key:
                        if result.errors:
                            breaker_record_failure(key)
                        else:
                            breaker_record_success(key)
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
                logger.warning(
                    "Scraper batch timed out after %ss, returning partial results",
                    batch_timeout,
                )
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
    quiet: bool = False,
) -> list[RankedJob]:
    ranked: list[RankedJob] = []
    for job in jobs:
        relevance = compute_relevance(job, profile)
        ranked.append((relevance["score"], job, relevance["reasons"]))
    ranked.sort(key=lambda x: x[0], reverse=True)

    # Phase 4 (§9.3): optional AI re-scoring for direct callers. The shared
    # pipeline (run_search) instead invokes _ai_rescore AFTER enrichment so
    # the AI judge sees real descriptions — never snippet noise.
    if use_ai:
        ranked = _ai_rescore(ranked, profile, ai_top_n, ai_timeout, quiet)

    # Phase 4 (§9.4): calibration guard on the FINAL scores (post-AI, so the
    # presented distribution is what we judge). Homogeneous scores mean the
    # heuristic couldn't separate signal; flag it and optionally spread them.
    ranked = _apply_flatline_guard(ranked, normalize_flatline)

    return ranked


def _apply_flatline_guard(ranked: list[RankedJob], normalize: bool) -> list[RankedJob]:
    """§9.4 — flag a homogeneous score distribution; optionally spread it.

    Shared by ``rank_jobs`` (heuristic/AI pass for direct callers) and
    ``run_search`` (final post-enrichment scores) so the calibration guard
    logic lives in exactly one place.
    """
    if detect_flatline([r[0] for r in ranked]):
        logger.warning(
            "Score distribution is flat (top-decile spread < %.1f) — results are "
            "homogeneous; enriched jobs should outrank snippet-guesses",
            5.0,
        )
        if normalize:
            scores = normalize_scores([r[0] for r in ranked])
            ranked = [(scores[i], ranked[i][1], ranked[i][2]) for i in range(len(ranked))]
    return ranked


def _ai_rescore(
    ranked: list[RankedJob],
    profile: dict[str, Any],
    ai_top_n: int = 30,
    ai_timeout: int = 60,
    quiet: bool = False,
) -> list[RankedJob]:
    """Phase 4 (§9.3) — AI re-scoring pass over eligible candidates.

    Judges only ``ai_eligible`` jobs (enriched/full descriptions — the AI
    prompt must never score bare snippet rows) and re-ranks by the AI
    verdict. Jobs whose call fails (budget, provider, parse) keep their
    heuristic score. Used by ``rank_jobs(use_ai=True)`` for direct callers
    and by ``run_search`` AFTER enrichment so the judge sees real data.
    """
    ai_idx = [i for i, (_, job, _) in enumerate(ranked) if ai_eligible(job)]
    ai_idx = ai_idx[: min(len(ai_idx), ai_top_n)]
    if not ai_idx:
        return ranked
    progress_ctx: Any = (
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
            transient=True,
        )
        if not quiet
        else _NullProgress()
    )
    with progress_ctx as progress:
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
                ai_relevance = f.result()
                if ai_relevance:
                    ranked[i] = (
                        ai_relevance["score"],
                        ranked[i][1],
                        ai_relevance["reasons"],
                    )
                progress.update(task, advance=1)
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def effective_query_caps(settings: dict[str, Any]) -> dict[str, int]:
    """Per-source query caps, adapted to the active Web Search backend.

    Returns ``scrapers.query_caps`` (or :data:`DEFAULT_QUERY_CAPS`) with the
    Web Search entry clamped to :data:`DDGS_WEB_SEARCH_CAP` when Exa is not
    configured (Session 29). Exa is one fast mcporter call per query, but the
    DDGS fallback fans out into 5 rate-limited site queries per search query
    — the raised cap would regularly blow the scraper batch timeout on the
    slow path. Read-only; never starts mcporter.
    """
    caps = dict((settings.get("scrapers") or {}).get("query_caps") or DEFAULT_QUERY_CAPS)
    from matcha.sources.backends.exa import exa_configured

    if not exa_configured():
        web = caps.get("Web Search")
        if web is not None and web > DDGS_WEB_SEARCH_CAP:
            caps["Web Search"] = DDGS_WEB_SEARCH_CAP
    return caps


def run_search(
    profile: dict[str, Any],
    query: str,
    location: str,
    days: int | None,
    settings: dict[str, Any],
    config: dict[str, Any],
    *,
    ai_enabled: bool = False,
    use_ai_queries: bool = True,
    enrich: bool = True,
    quiet: bool = False,
) -> dict[str, Any]:
    """One pass through the full pipeline (Phase 6, strategy §13).

    profile → queries (AI expansion) → search → normalize → central filters
    → rank → enrich top N. Shared by the TUI run loop and the headless
    ``search``/``watch``/MCP surfaces so every front-end is identical.
    ``quiet=True`` suppresses all console UI (JSON-safe stdout).
    """
    ai_top_n = int(settings.get("ai", {}).get("top_n", 30))
    ai_timeout = int(settings.get("ai", {}).get("timeout", 60))
    ai_max_calls = int(settings.get("ai", {}).get("max_calls", 60))
    # Phase 5 (§10.2): fresh AI budget per run (queries + scoring share it).
    reset_budget(max_calls=ai_max_calls)

    queries = [query]
    if ai_enabled and use_ai_queries:
        if not quiet:
            console.print("[yellow]Generating AI-powered search queries...[/yellow]")
        ai_queries = ai_generate_queries(profile)
        if ai_queries:
            extra = [q for q in ai_queries if q.lower() != query.lower()]
            if extra:
                extra = _dedup_queries(extra)
                extra = _validate_queries(extra)
                queries.extend(extra)
                if extra and not quiet:
                    console.print(f"[dim]AI queries: {', '.join(queries)}[/dim]")

    max_pages = int(settings.get("search", {}).get("max_pages", 2))
    indeed_domain = settings.get("scrapers", {}).get("indeed_domain", "in.indeed.com")

    # Phase 7 (strategy §6.2): the RSS source runs only when feeds are
    # configured (settings sources.rss.feeds) — zero config means it stays
    # off and doctor reports so.
    extra_scrapers: dict[str, Any] = {}
    extra_scraper_kwargs: dict[str, dict[str, Any]] = {}
    sources_cfg = settings.get("sources")
    if isinstance(sources_cfg, dict):
        rss_cfg = sources_cfg.get("rss")
        if isinstance(rss_cfg, dict):
            rss_feeds = [
                str(f) for f in rss_cfg.get("feeds", []) if isinstance(f, str) and f.strip()
            ]
            if rss_feeds:
                from matcha.sources.rss import search_rss_jobs

                extra_scrapers["RSS"] = search_rss_jobs
                extra_scraper_kwargs["RSS"] = {"feeds": rss_feeds}
    # Phase 1 opt-in: 200+ employer career boards via DDGS. Off by default so
    # zero-config runs stay fast; doctor reports `off` until enabled.
    scrapers_cfg = settings.get("scrapers")
    if isinstance(scrapers_cfg, dict) and scrapers_cfg.get("career_sites", False):
        from matcha.sources.career_sites import search_career_sites_jobs

        extra_scrapers["Career Sites"] = search_career_sites_jobs

    # Session 21/28/29: per-source query caps — how many of the (up to 6) AI
    # queries each source runs. Defaults live in settings.DEFAULT_QUERY_CAPS
    # (raised Web Search 3 -> 6 once Exa became the primary backend: one fast
    # mcporter call per query). Adaptive: when Exa is not configured, Web
    # Search runs the slow DDGS path and its cap is clamped back to 3.
    # Overridable via scrapers.query_caps.
    query_caps = effective_query_caps(settings)
    batch_timeout = int(
        (settings.get("search") or {}).get("batch_timeout", DEFAULT_BATCH_TIMEOUT)
    )
    jobs, source_counts, source_errors = search_jobs(
        queries,
        location,
        days=days,
        max_pages=max_pages,
        indeed_domain=indeed_domain,
        quiet=quiet,
        extra_scrapers=extra_scrapers or None,
        extra_scraper_kwargs=extra_scraper_kwargs or None,
        query_caps=query_caps,
        batch_timeout=batch_timeout,
    )
    found_count = len(jobs)

    filter_summary = ""
    if jobs:
        filters_cfg = dict(settings.get("filters", {}))
        if days is not None:
            filters_cfg["days"] = days
        if not quiet:
            with console.status("[yellow]Filtering results...[/yellow]"):
                jobs = normalize_jobs(jobs)
                jobs, filter_reports = apply_filters(jobs, profile, filters_cfg)
        else:
            jobs = normalize_jobs(jobs)
            jobs, filter_reports = apply_filters(jobs, profile, filters_cfg)
        filter_summary = build_filter_summary(filter_reports)
        notes = filter_notes(filter_reports)
    else:
        notes = []

    # Heuristic ranking first. The AI re-scoring pass runs AFTER enrichment
    # (see below) so the AI judge scores real descriptions (§9.3).
    normalize_flatline = settings.get("ranking", {}).get("normalize_scores", False)
    ranked = rank_jobs(
        jobs,
        profile,
        use_ai=False,
        ai_top_n=ai_top_n,
        ai_timeout=ai_timeout,
        normalize_flatline=False,
        quiet=quiet,
    )

    enriched_count = 0
    enrich_cfg = settings.get("enrichment", {})
    if enrich and enrich_cfg.get("enabled", True) and ranked:
        from matcha.sources.enrichment import enrich_top_n

        enrich_top = int(enrich_cfg.get("top_n", 30))
        enrich_workers = int(enrich_cfg.get("max_workers", 5))
        enrich_timeout = int(enrich_cfg.get("timeout", 30))
        if not quiet:
            with console.status("[yellow]Enriching top jobs with full details...[/yellow]"):
                enriched_count, ranked = enrich_top_n(
                    ranked,
                    top_n=enrich_top,
                    max_workers=enrich_workers,
                    timeout=enrich_timeout,
                    config=config,
                )
        else:
            enriched_count, ranked = enrich_top_n(
                ranked,
                top_n=enrich_top,
                max_workers=enrich_workers,
                timeout=enrich_timeout,
                config=config,
            )
        if enriched_count and not quiet:
            console.print(
                f"[dim]Enriched [cyan]{enriched_count}[/cyan] top jobs with details[/dim]"
            )

    # Phase 4 (§9.3): AI re-scoring AFTER enrichment — the judge now sees the
    # detail pass's descriptions/salary/location, never snippet noise. Only
    # eligible (enriched) candidates are judged; failures keep heuristic scores.
    if ai_enabled and ranked:
        ranked = _ai_rescore(ranked, profile, ai_top_n=ai_top_n, ai_timeout=ai_timeout, quiet=quiet)

    # §9.4 calibration guard on the FINAL scores (post-AI, post-enrichment).
    ranked = _apply_flatline_guard(ranked, normalize_flatline)

    # Phase 3-adjacent polish (§9.5): optional go/no-go verdict for the top-K
    # enriched candidates — one extra prompt, gated on AI, budget-limited,
    # cached. Stamped onto each job dict (surfaces in the detail panel AND in
    # `search --json`/`watch` for agents); never blocks on empty candidates.
    verdict_count = 0
    verdict_k = int(settings.get("ai", {}).get("verdict_k", 5) or 0)
    if ai_enabled and verdict_k > 0 and ranked:
        verdict_idx = [i for i, (_, job, _) in enumerate(ranked) if ai_eligible(job)]
        verdict_idx = verdict_idx[: min(len(verdict_idx), verdict_k)]
        if verdict_idx:
            v_progress_ctx: Any = (
                Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    console=console,
                    transient=True,
                )
                if not quiet
                else _NullProgress()
            )
            with v_progress_ctx as progress:
                v_task = progress.add_task(
                    "[yellow]Verdict on top candidates...", total=len(verdict_idx)
                )
                with ThreadPoolExecutor(max_workers=min(len(verdict_idx), 5)) as v_executor:
                    v_futures = {
                        v_executor.submit(ai_verdict, profile, ranked[i][1], timeout=ai_timeout): i
                        for i in verdict_idx
                    }
                    for f in as_completed(v_futures):
                        i = v_futures[f]
                        v = f.result()
                        if v:
                            ranked[i][1]["verdict"] = v
                            verdict_count += 1
                        progress.update(v_task, advance=1)

    return {
        "ranked": ranked,
        "source_counts": source_counts,
        "source_errors": source_errors,
        "filter_summary": filter_summary,
        "filter_notes": notes,
        "found_count": found_count,
        "ai_used": ai_enabled,
        "ai_budget_used": budget_used(),
        "enriched_count": enriched_count,
        "verdict_count": verdict_count,
    }


def _job_json(score: float, job: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    """One ranked job as a JSON-safe dict (job fields + match_score + reasons)."""
    out = dict(job)
    out["match_score"] = round(float(score), 1)
    out["reasons"] = list(reasons)
    return out


def build_search_payload(
    query: str,
    location: str,
    days: int | None,
    run_result: dict[str, Any],
    command: str = "search",
) -> dict[str, Any]:
    """The structured JSON document for search/watch/MCP output (strategy §13)."""
    return {
        "command": command,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "location": location,
        "days": days,
        "ai_used": bool(run_result.get("ai_used")),
        "ai_budget_used": int(run_result.get("ai_budget_used", 0)),
        "source_counts": dict(run_result.get("source_counts", {})),
        "source_errors": {str(k): list(v) for k, v in run_result.get("source_errors", {}).items()},
        "filter_summary": run_result.get("filter_summary", ""),
        "filter_notes": list(run_result.get("filter_notes", [])),
        "found_count": int(run_result.get("found_count", 0)),
        "enriched_count": int(run_result.get("enriched_count", 0)),
        "verdict_count": int(run_result.get("verdict_count", 0)),
        "jobs": [
            _job_json(score, job, reasons) for score, job, reasons in run_result.get("ranked", [])
        ],
    }


def _print_human_summary(
    run_result: dict[str, Any],
    top: int = 10,
    extra: list[RankedJob] | None = None,
    header: str = "",
) -> None:
    """Compact human-readable summary (search/watch without --json)."""
    ranked = run_result.get("ranked", []) if extra is None else extra
    if header:
        console.print(header)
    source_parts = [
        f"[cyan]{count}[/] from [bold]{name}[/]"
        for name, count in sorted(run_result.get("source_counts", {}).items())
        if count > 0
    ]
    if source_parts:
        console.print("  " + " | ".join(source_parts))
    if run_result.get("filter_summary"):
        console.print(f"  [dim]Filtered: {len(ranked)} kept ({run_result['filter_summary']})[/dim]")
    for note in run_result.get("filter_notes", []):
        console.print(f"  [dim]{note}[/dim]")
    if run_result.get("ai_budget_used"):
        console.print(f"  [dim]AI budget: {run_result['ai_budget_used']} used[/dim]")
    if not ranked:
        if extra is not None:
            console.print("  [dim]No new jobs.[/dim]")
        else:
            console.print("[yellow]No jobs.[/yellow]")
        return
    shown = ranked[:top]
    console.print(f"  [bold]Top {len(shown)} of {len(ranked)}:[/bold]")
    for i, (score, job, _reasons) in enumerate(shown, 1):
        tags = "".join(f"[dim]\\[{t}][/dim]" for t in provenance_tags(job))
        console.print(
            f"  {i:>3}. {job.get('title', 'N/A')} @ {job.get('company', 'N/A')} — "
            f"{job.get('source', '?')} — [{score:.1f}%]{tags}"
        )


def _emit_json(
    args: argparse.Namespace,
    doc: dict[str, Any],
    run_result: dict[str, Any],
    extra: list[RankedJob] | None = None,
    header: str = "",
) -> None:
    """Shared search/watch output: JSON to stdout/file and/or human summary."""
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if getattr(args, "output", None):
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        # stderr: `matcha search --json --output x.json` / `watch --json`
        # must keep stdout a pure JSON stream (reviewer-caught in Phase 6).
        _err_console.print(f"[dim]Wrote {out.resolve()}[/dim]")
    if getattr(args, "json", False):
        print(text)
    else:
        _print_human_summary(run_result, top=getattr(args, "top", 10), extra=extra, header=header)


def _headless_credentials(
    args: argparse.Namespace, settings: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], str, str, int | None, bool]:
    """Shared search/watch preamble: profile, config, query, location, days, ai."""
    profile = load_profile()
    if not profile:
        console.print(
            "[red]No saved profile found. Run `matcha` once interactively "
            "(or `matcha --new-profile`) to create one.[/red]"
        )
        sys.exit(1)
    config = load_config()
    query = (
        args.query or settings.get("search", {}).get("query", "") or config.get("last_query", "")
    )
    if args.location is not None:
        location = args.location
    else:
        location = (
            settings.get("search", {}).get("location", "") or config.get("last_location", "") or ""
        )
    if args.days is not None:
        days = max(0, int(args.days))
    else:
        days = config.get("last_days") or settings.get("search", {}).get("days", 7)
    if not query:
        console.print("[red]No query. Use --query or set `search.query` in the YAML config.[/red]")
        sys.exit(1)
    # Session 22 (user-driven): the interactive TUI sets profile["location"]
    # from the prompt so the location filter is active; headless runs must do
    # the same or `search -l`/watch/MCP silently skip the location stage
    # (profile location is often empty -> every job kept, US jobs included).
    if location and profile:
        profile["location"] = location
    ai_enabled = check_ai_available() and settings.get("ai", {}).get("enabled", True)
    return profile, config, query, location, days, ai_enabled


def cmd_search(args: argparse.Namespace, settings: dict[str, Any]) -> None:
    """`matcha search` — one headless ranked search (JSON-capable)."""
    profile, config, query, location, days, ai_enabled = _headless_credentials(args, settings)
    run_result = run_search(
        profile,
        query,
        location,
        days,
        settings,
        config,
        ai_enabled=ai_enabled,
        use_ai_queries=not args.no_ai_queries,
        enrich=not args.no_enrich,
        quiet=True,
    )
    doc = build_search_payload(query, location, days, run_result, command="search")
    _emit_json(args, doc, run_result)


def cmd_watch(args: argparse.Namespace, settings: dict[str, Any]) -> None:
    """`matcha watch` — headless search that surfaces only NEW jobs.

    Marks every result URL as seen (unless ``--no-mark-seen``) and writes
    the full JSON document to ``--output`` (default ``~/.matcha/latest.json``)
    so cron/agent loops can diff across runs.
    """
    profile, config, query, location, days, ai_enabled = _headless_credentials(args, settings)
    run_result = run_search(
        profile,
        query,
        location,
        days,
        settings,
        config,
        ai_enabled=ai_enabled,
        use_ai_queries=not args.no_ai_queries,
        enrich=not args.no_enrich,
        quiet=True,
    )
    ranked = run_result["ranked"]
    jobs = [job for _score, job, _reasons in ranked]
    new_jobs, seen_jobs = partition_new(jobs)
    ranked_by_id = {id(job): (score, job, reasons) for score, job, reasons in ranked}
    new_ranked = [ranked_by_id[id(job)] for job in new_jobs if id(job) in ranked_by_id]

    if args.no_mark_seen:
        marked = 0
    else:
        marked = mark_seen(jobs)

    doc = build_search_payload(query, location, days, run_result, command="watch")
    doc["new_count"] = len(new_jobs)
    doc["seen_count"] = len(seen_jobs)
    doc["new_jobs"] = [_job_json(score, job, reasons) for score, job, reasons in new_ranked]
    doc["seen_urls_total"] = track_stats()["seen_urls_total"]
    doc["marked_seen"] = marked

    if args.output is None:
        args.output = str(Path.home() / ".matcha" / "latest.json")
    header = (
        f"[bold]Watch: {len(new_jobs)} new[/bold] "
        f"({len(seen_jobs)} previously seen, {len(jobs)} total)"
    )
    _emit_json(args, doc, run_result, extra=new_ranked, header=header)


def cmd_github(args: argparse.Namespace) -> None:
    """`matcha github enrich` — merge GitHub profile signals into profile.json.

    Optional (strategy §11, Phase 7): reads ``gh api user`` + ``user/repos``
    read-only and appends ``github_username`` + language/topic-derived skill
    suggestions. Requires gh installed + authenticated (env token or
    hosts.yml) — never runs ``gh auth status``.
    """
    from matcha.profile import enrich_github_profile

    profile = load_profile()
    if not profile:
        console.print(
            "[red]No saved profile found. Run `matcha` once interactively "
            "(or `matcha --new-profile`) to create one.[/red]"
        )
        sys.exit(1)
    enriched = enrich_github_profile(profile)
    if not enriched:
        console.print(
            "[yellow]GitHub enrichment unavailable — install `gh` and authenticate "
            "(`gh auth login`), then try again.[/yellow]"
        )
        return
    save_profile(enriched)
    added = len(enriched.get("skills", [])) - len(profile.get("skills", []))
    username = enriched.get("github_username", "")
    suffix = f", +{added} suggested skill(s)" if added else ""
    console.print(f"[green]GitHub enrichment saved:[/green] username={username or '?'}{suffix}")


def cmd_skill(args: argparse.Namespace) -> None:
    """`matcha skill` — install/uninstall the agent skill (SKILL.md)."""
    from matcha.skill import default_destinations, install_skill, uninstall_skill

    dests = [Path(args.dest)] if args.dest else default_destinations()
    if args.install:
        for dest in dests:
            out = install_skill(dest)
            console.print(f"[green]Installed skill → {out}[/green]")
    elif args.uninstall:
        for dest in dests:
            if uninstall_skill(dest):
                console.print(f"[dim]Removed {dest}[/dim]")
            else:
                console.print(f"[dim]Nothing to remove at {dest}[/dim]")
    else:
        console.print("Usage: matcha skill --install [--dest PATH] | --uninstall [--dest PATH]")


def cmd_mcp() -> None:
    """`matcha mcp` — run the optional MCP server (stdio transport)."""
    from matcha import mcp_server

    mcp_server.run()


def build_results_table(
    ranked: list[RankedJob],
    page: int,
    page_size: int,
    total_pages: int,
    ai_enabled: bool,
    saved_ids: dict[str, Any],
    highlight: int | None = None,
    seen_ids: set[int] | None = None,
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
    table.add_column("Match", justify="right", width=20, no_wrap=True)

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
        # Session 20: tag text must be rich-escaped (\[..\]) or rich treats
        # [full]/[snippet] as unknown styles and renders nothing — the tags
        # were invisible in every table before this fix.
        tags = "".join(f"[dim]\\[{t}][/dim]" for t in provenance_tags(job))
        seen_mark = " [dim]\\[seen][/dim]" if seen_ids and id(job) in seen_ids else ""
        row_style = (
            "reverse bold" if highlight is not None and (i - 1) == (start + highlight) else None
        )
        table.add_row(
            str(i),
            job.get("title", "N/A") + saved_mark + seen_mark,
            job.get("company", "N/A"),
            job.get("source", "N/A"),
            f"[{score_color}]{score}%[/{score_color}]{tags}",
            style=row_style,
        )

    return table


def _saved_salary(entry: dict[str, Any]) -> str:
    """Saved-view Salary cell: the raw string, else the LPA number."""
    salary = str(entry.get("salary") or "").strip()
    if salary:
        return salary[:12]
    sal_int = entry.get("salary_int")
    if isinstance(sal_int, (int, float)) and sal_int > 0:
        return f"{int(sal_int)} LPA"
    return ""


def _saved_posted(entry: dict[str, Any]) -> str:
    """Saved-view Posted cell: compact relative age from ``listed_epoch``."""
    epoch = entry.get("listed_epoch")
    if not isinstance(epoch, (int, float)) or not epoch:
        return ""
    days = int((time.time() - float(epoch)) // 86400)
    if days <= 0:
        return "today"
    return f"{days}d"


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
    verdict = job.get("verdict")
    if isinstance(verdict, dict) and verdict.get("line"):
        mark = "[green]✓ Recommend[/green]" if verdict.get("recommend") else "[red]✗ Pass[/red]"
        lines.append(f"[cyan]Verdict:[/cyan] {mark} — {verdict['line']}")
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


def _visible_ranked(
    ranked: list[RankedJob], seen_ids: set[int], show_seen: bool
) -> list[RankedJob]:
    """The rows to render: all when ``show_seen``, else un-seen jobs only.

    Session 20: the interactive TUI hides jobs the user has already seen
    (recorded in ``seen_urls``) by default so re-runs surface new postings
    instead of replaying the same list; ``h`` flips ``show_seen``.
    """
    if show_seen or not seen_ids:
        return ranked
    return [r for r in ranked if id(r[1]) not in seen_ids]


def prompt_loop(
    ranked: list[RankedJob],
    source_counts: dict[str, int],
    source_errors: dict[str, list[str]],
    ai_enabled: bool,
    filter_summary: str = "",
    filter_notes: list[str] | None = None,
    seen_ids: set[int] | None = None,
) -> str | None:
    if not ranked:
        console.print("[yellow]No jobs found. Try different search terms.[/yellow]")
        return None

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
    for note in filter_notes or []:
        console.print(f"  [dim]{note}[/dim]")
    if error_parts:
        console.print("  [bold]Errors:[/bold] " + " | ".join(error_parts))

    page_size = 10
    saved_ids = load_saved_jobs()

    class State:
        page: int = 0
        selected: int = 0
        mode: str = "list"
        detail_idx: int = 0
        re_run: bool = False
        show_seen: bool = False

    st = State()
    seen_ids = seen_ids or set()

    def _visible() -> list[RankedJob]:
        return _visible_ranked(ranked, seen_ids, st.show_seen)

    def _total_pages() -> int:
        return max(1, (len(_visible()) + page_size - 1) // page_size)

    hidden_count = len(ranked) - len(_visible_ranked(ranked, seen_ids, False))
    all_seen = bool(ranked) and hidden_count == len(ranked)
    if hidden_count and not all_seen:
        console.print(f"  [dim]{hidden_count} already seen — hidden ([bold]h[/bold] to show)[/dim]")
    if all_seen:
        # Session 21 (user-driven): never re-show the same list — the user
        # asked for fresh jobs, not a replay. The empty state guides the
        # next step; `h` reveals the previously-seen rows on demand.
        console.print(
            "  [yellow]No new jobs — all results were already shown in a previous run.[/yellow] "
            "([bold]h[/bold] view them, [bold]r[/bold] search again, [bold]q[/bold] quit)"
        )

    help_text = (
        "[dim]\u2191\u2193[/dim] navigate  [dim]Enter[/dim] detail  "
        "[dim]s[/dim] save/unsave  [dim]o[/dim] open  "
        "[dim]n[/dim]/[dim]p[/dim] page  [dim]h[/dim] seen  "
        "[dim]l[/dim] saved  [dim]r[/dim] re-run  [dim]q[/dim] quit"
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
            # Mirror the persisted enriched row into the live view so the
            # Saved screen shows salary/posted immediately (strategy §8).
            saved_ids[url] = job_entry(job)
            # Session 20: a saved (applied-to) job must not resurface in the
            # next run — retire it from the seen table now.
            mark_seen([job])

    def _render_content():
        with console.capture() as cap:
            if st.mode == "detail":
                score, job, reasons = _visible()[st.detail_idx]
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
                    t.add_column("Title", width=28, overflow="ellipsis")
                    t.add_column("Company", width=14, overflow="ellipsis")
                    t.add_column("Salary", width=12)
                    t.add_column("Posted", width=8)
                    t.add_column("Source", width=10)
                    for entry in saved_ids.values():
                        t.add_row(
                            entry.get("title", ""),
                            entry.get("company", ""),
                            _saved_salary(entry),
                            _saved_posted(entry),
                            entry.get("source", ""),
                        )
                    console.print(t)
            else:
                visible = _visible()
                if not visible:
                    console.print(
                        "[yellow]No new jobs.[/yellow] All results were already shown in a "
                        "previous run — press [bold]h[/bold] to view them anyway, "
                        "[bold]r[/bold] to search again, or [bold]q[/bold] to quit."
                    )
                else:
                    console.print(
                        build_results_table(
                            visible,
                            st.page,
                            page_size,
                            _total_pages(),
                            ai_enabled,
                            saved_ids,
                            highlight=st.selected,
                            seen_ids=seen_ids,
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
            pc = min(page_size, len(_visible()) - st.page * page_size)
            st.selected = pc - 1
        event.app.invalidate()

    @kb.add("down")
    def _down(event):
        if st.mode != "list":
            return
        ps = st.page * page_size
        pe = min(ps + page_size, len(_visible()))
        if st.selected < pe - ps - 1:
            st.selected += 1
        elif st.page + 1 < _total_pages():
            st.page += 1
            st.selected = 0
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event):
        if st.mode in ("detail", "saved"):
            st.mode = "list"
        else:
            idx = st.page * page_size + st.selected
            if 0 <= idx < len(_visible()):
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
        if st.mode == "list" and st.page + 1 < _total_pages():
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

    @kb.add("h")
    @kb.add("H")
    def _toggle_seen(event):
        if st.mode == "list":
            st.show_seen = not st.show_seen
            st.page = 0
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
        if 0 <= idx < len(_visible()):
            _do_save(_visible()[idx][1])
        event.app.invalidate()

    @kb.add("o")
    @kb.add("O")
    def _open(event):
        idx = -1
        if st.mode == "list":
            idx = st.page * page_size + st.selected
        elif st.mode == "detail":
            idx = st.detail_idx
        if 0 <= idx < len(_visible()):
            job = _visible()[idx][1]
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

    app: Any = Application(
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
    return None


def run() -> None:
    parser = argparse.ArgumentParser(
        description="Matcha \u2014 multi-source job search with relevance ranking"
    )
    subparsers = parser.add_subparsers(dest="command")
    doctor_parser = subparsers.add_parser("doctor", help="Check job-source health")
    doctor_parser.add_argument("--json", action="store_true", help="Emit the report as JSON")

    # Phase 6 (strategy §13): agent + automation surface.
    search_parser = subparsers.add_parser(
        "search", help="Headless ranked job search (JSON-capable)"
    )
    search_parser.add_argument("-q", "--query", type=str, default=None)
    search_parser.add_argument("-l", "--location", type=str, default=None)
    search_parser.add_argument("-d", "--days", type=int, default=None)
    search_parser.add_argument(
        "--json", action="store_true", help="Emit the result document as JSON on stdout"
    )
    search_parser.add_argument(
        "--output", type=str, default=None, help="Also write the JSON document to this file"
    )
    search_parser.add_argument(
        "--top", type=int, default=10, help="Length of the human summary (default 10)"
    )
    search_parser.add_argument(
        "--no-ai-queries", action="store_true", help="Skip AI query expansion"
    )
    search_parser.add_argument("--no-enrich", action="store_true", help="Skip top-N enrichment")

    watch_parser = subparsers.add_parser(
        "watch", help="One-shot search that surfaces only NEW jobs"
    )
    watch_parser.add_argument("-q", "--query", type=str, default=None)
    watch_parser.add_argument("-l", "--location", type=str, default=None)
    watch_parser.add_argument("-d", "--days", type=int, default=None)
    watch_parser.add_argument(
        "--json", action="store_true", help="Emit the result document as JSON on stdout"
    )
    watch_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="JSON output file (default ~/.matcha/latest.json)",
    )
    watch_parser.add_argument("--top", type=int, default=10)
    watch_parser.add_argument("--no-ai-queries", action="store_true")
    watch_parser.add_argument("--no-enrich", action="store_true")
    watch_parser.add_argument(
        "--no-mark-seen", action="store_true", help="Don't record results in seen_urls"
    )

    skill_parser = subparsers.add_parser(
        "skill", help="Install/uninstall the agent skill (SKILL.md)"
    )
    skill_parser.add_argument("--install", action="store_true", help="Install the skill")
    skill_parser.add_argument("--uninstall", action="store_true", help="Remove an installed skill")
    skill_parser.add_argument("--dest", type=str, default=None, help="Explicit install path")

    subparsers.add_parser("mcp", help="Run the optional MCP server (stdio transport)")

    github_parser = subparsers.add_parser(
        "github", help="Optional GitHub profile enrichment (strategy §11)"
    )
    github_parser.add_argument(
        "action",
        choices=["enrich"],
        nargs="?",
        default="enrich",
        help="enrich: merge gh signals into profile.json",
    )

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

    # Phase 6 (strategy §13): headless agent + automation commands.
    if args.command == "search":
        cmd_search(args, load_settings(config_path=args.config))
        return
    if args.command == "watch":
        cmd_watch(args, load_settings(config_path=args.config))
        return
    if args.command == "skill":
        cmd_skill(args)
        return
    if args.command == "mcp":
        cmd_mcp()
        return
    if args.command == "github":
        cmd_github(args)
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

        # Phase 6 (strategy §13): the same pipeline every front-end runs.
        run_result = run_search(
            profile,
            query,
            location,
            days,
            settings,
            config,
            ai_enabled=use_ai,
            use_ai_queries=True,
            enrich=True,
            quiet=False,
        )
        ranked = run_result["ranked"]
        source_counts = run_result["source_counts"]
        source_errors = run_result["source_errors"]
        filter_summary = run_result["filter_summary"]

        if not run_result["found_count"]:
            console.print("[yellow]No jobs found. Try different search terms.[/yellow]")
            result = Prompt.ask("Search again?", default="y")
            if result.lower() in ("y", "yes"):
                continue
            break
        if not ranked:
            console.print("[yellow]No jobs survived the filters.[/yellow]")
            if filter_summary:
                console.print(f"  [dim]Dropped: {filter_summary}[/dim]")
            result = Prompt.ask("Search again?", default="y")
            if result.lower() in ("y", "yes"):
                continue
            break

        # Phase 5 (§10.2): surface the budget guard outcome in the run summary.
        ai_calls = run_result["ai_budget_used"]
        if use_ai and ai_calls:
            max_calls = settings.get("ai", {}).get("max_calls", 60)
            remaining = max(0, max_calls - ai_calls)
            console.print(
                f"[dim]AI budget: {ai_calls}/{max_calls} calls used ({remaining} left)[/dim]"
            )

        jobs_all = [job for _score, job, _reasons in ranked]
        _, seen_jobs = partition_new(jobs_all)
        seen_ids = {id(j) for j in seen_jobs}

        loop_result = prompt_loop(
            ranked,
            source_counts,
            source_errors,
            ai_enabled=use_ai,
            filter_summary=filter_summary,
            filter_notes=run_result.get("filter_notes", []),
            seen_ids=seen_ids,
        )

        # Session 20: interactive runs record what was shown so the next run
        # hides already-seen jobs instead of replaying the same list (watch
        # already did this; the TUI now joins it).
        mark_seen(jobs_all)

        if loop_result != "re_run":
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
