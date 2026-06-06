import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ai import ai_extract_profile, ai_suggest_titles, check_ai_available
from config import load_profile, save_profile
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

console = Console()


def extract_experience(text_lower: str) -> Optional[int]:
    years = re.findall(
        r"(\d+)\+?\s*(?:years?|yrs?|yr)\s*(?:of)?\s*(?:experience|exp|work)?", text_lower
    )
    if years:
        return max(int(y) for y in years)
    exp = re.findall(r"(?:experience|exp)\s*(?:of|:)?\s*(\d+)", text_lower)
    if exp:
        return max(int(e) for e in exp)
    return None


def parse_resume_pdf(path: str) -> Optional[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        return None

    try:
        import pdfplumber
    except ImportError:
        console.print("[red]pdfplumber not installed. Run: pip install pdfplumber[/red]")
        return None

    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        console.print(f"[red]Error reading PDF: {e}[/red]")
        return None

    if not text.strip():
        console.print(
            "[yellow]Could not extract text from PDF.[/yellow]\n"
            "  If this is a scanned document, install PaddleOCR:\n"
            "  pip install paddleocr\n"
            "  Or enter your profile manually."
        )
        return None

    if not check_ai_available():
        console.print("[red]AI not configured for resume parsing.[/red]")
        console.print("  Set $AI_API_KEY, $AI_API_URL, and $AI_MODEL, or run with --configure")
        console.print("  [yellow]Falling back to manual entry...[/yellow]")
        return None

    from concurrent.futures import ThreadPoolExecutor

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("[yellow]Extracting profile with AI...", total=None)
        ai_profile = ai_extract_profile(text[:4000])
    if not ai_profile:
        console.print("[red]AI profile extraction failed.[/red]")
        console.print("  Check that your AI provider is reachable and the model supports structured output.")
        console.print("  [yellow]Falling back to manual entry...[/yellow]")
        return None

    text_lower = text.lower()
    name = ai_profile.get("name", "") or text.split("\n")[0].strip()
    title = ai_profile.get("title", "")
    headline = ai_profile.get("headline", title)
    skills = ai_profile.get("skills", [])
    experience = ai_profile.get("experience", "")
    summary = ai_profile.get("summary", "")

    fallback_exp = extract_experience(text_lower)
    if fallback_exp and not experience:
        experience = str(fallback_exp)

    profile = {
        "name": name,
        "title": title,
        "headline": headline,
        "skills": skills,
        "experience": str(experience) if experience else "",
        "summary": summary,
    }

    table = Table(box=None, show_header=False, show_edge=False, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Name", profile["name"])
    table.add_row(
        "Title",
        profile["title"] if profile["title"] else "[yellow]Not detected[/yellow]",
    )
    table.add_row(
        "Skills",
        f"{len(profile['skills'])} detected: {', '.join(profile['skills'])}"
        if profile["skills"]
        else "[yellow]None detected[/yellow]",
    )
    table.add_row(
        "Experience",
        f"~{profile['experience']} years"
        if profile.get("experience")
        else "[yellow]Not detected[/yellow]",
    )
    console.print("\n[green]Resume parsed:[/green]")
    console.print(table)

    return profile


HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_linkedin_username(url: str) -> Optional[str]:
    match = re.search(r"linkedin\.com/in/([^/]+)", url)
    return match.group(1) if match else None


def search_linkedin_profile_via_web(username: str) -> Optional[dict[str, Any]]:
    queries = [
        f"linkedin.com/in/{username}",
        f"{username.replace('-', ' ')} linkedin",
    ]
    found = None

    for query in queries:
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select(".result")
            for result in results:
                if result.select_one(".badge--ad"):
                    continue
                title_el = result.select_one(".result__title a")
                snippet_el = result.select_one(".result__snippet")
                if not title_el:
                    continue
                raw_href = title_el.get("href", "")
                actual_url = extract_url(raw_href) if raw_href else ""
                if (
                    username.lower() not in actual_url.lower()
                    and "linkedin.com/in/" not in actual_url.lower()
                ):
                    continue
                found = result
                break
            if found:
                break
        except requests.RequestException:
            continue

    if not found:
        return None

    title_el = found.select_one(".result__title a")
    snippet_el = found.select_one(".result__snippet")
    title_text = title_el.get_text(strip=True)
    snippet = snippet_el.get_text(strip=True) if snippet_el else ""

    name = title_text.split(" - ")[0].strip() if " - " in title_text else username
    headline = ""
    if " - " in title_text and " | " in title_text:
        headline = title_text.split(" | ")[0].split(" - ", 1)[-1].strip()

    title_candidates = re.findall(
        r"(DevOps\s*(?:Engineer|Developer)?|Software\s*(?:Engineer|Developer|Architect)"
        r"|Cloud\s*Engineer|SRE|Site\s*Reliability|Platform\s*Engineer"
        r"|Data\s*(?:Engineer|Scientist|Analyst)|ML\s*Engineer"
        r"|Full.?Stack|Frontend|Backend|Product\s*Manager"
        r"|Engineering\s*Manager|Tech\s*Lead)",
        snippet,
        re.IGNORECASE,
    )
    if title_candidates:
        headline = title_candidates[0].strip()
    elif "Experience:" in snippet:
        exp_match = re.search(r"Experience:\s*([^·]+)", snippet)
        if exp_match:
            headline = exp_match.group(1).strip()

    if check_ai_available():
        ai_result = ai_extract_profile(
            f"Name: {name}\nHeadline: {headline}\nSummary: {snippet[:2000]}"
        )
        if ai_result:
            skills = ai_result.get("skills", [])
            return {
                "name": name,
                "headline": ai_result.get("headline", headline),
                "skills": skills,
                "summary": snippet,
                "experience": ai_result.get("experience", ""),
            }

    return {
        "name": name,
        "headline": headline,
        "skills": [],
        "summary": snippet,
        "experience": "",
    }


def extract_url(raw_href: str) -> str:
    from urllib.parse import parse_qs, unquote

    if raw_href.startswith("//"):
        raw_href = "https:" + raw_href
    parsed = urlparse(raw_href)
    if "duckduckgo.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            return unquote(uddg)
    return raw_href


def scrape_linkedin_profile(url: str) -> Optional[dict[str, Any]]:
    username = extract_linkedin_username(url)
    if not username:
        console.print("[red]Invalid LinkedIn profile URL[/red]")
        return None

    console.print(f"[yellow]Fetching LinkedIn profile: {username}...[/yellow]")

    try:
        resp = requests.get(
            f"https://www.linkedin.com/in/{username}",
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return search_linkedin_profile_via_web(username)

        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("title")
        full_name = None
        headline = None

        if title_tag:
            title_text = title_tag.get_text(strip=True)
            parts = title_text.split(" | ")
            if len(parts) >= 2:
                full_name = parts[0].strip()
                headline = parts[1].strip()

        about_section = soup.find("section", {"id": "about"})
        summary = ""
        if about_section:
            summary = about_section.get_text(strip=True)

        skills = []
        skills_section = soup.find("section", {"id": "skills"})
        if skills_section:
            for li in skills_section.find_all("li"):
                skills.append(li.get_text(strip=True))

        if not full_name or not soup.find("main"):
            return search_linkedin_profile_via_web(username)

        return {
            "name": full_name or username,
            "headline": headline or "",
            "summary": summary,
            "skills": skills,
            "experience": "",
        }

    except requests.RequestException:
        return search_linkedin_profile_via_web(username)


def manual_profile_entry() -> dict[str, Any]:
    console.print(Panel("[bold]Enter Your Profile Details[/bold]"))
    name = Prompt.ask("Full name")
    title = Prompt.ask("Current/Past job title")
    headline = Prompt.ask("Professional headline (one-liner)", default=title)
    skills_input = Prompt.ask("Skills (comma-separated)")
    skills = [s.strip() for s in skills_input.split(",") if s.strip()]
    experience = Prompt.ask("Years of experience")
    summary = Prompt.ask("Professional summary (brief description of your background)")
    return {
        "name": name,
        "title": title,
        "headline": headline,
        "skills": skills,
        "experience": experience,
        "summary": summary,
    }


def build_or_load_profile(force_new: bool = False) -> Optional[dict[str, Any]]:
    if not force_new:
        existing = load_profile()
        if existing:
            name = existing.get("name", "").strip() or "User"
            title = existing.get("title") or existing.get("headline") or ""
            skill_count = len(existing.get("skills", []))
            exp = existing.get("experience", "") or ""
            info = name
            if title:
                info += f" — {title}"
            info += f" ({skill_count} skills"
            if exp:
                info += f", ~{exp}y exp"
            info += ")"
            console.print(f"[dim]Profile: {info}[/dim]")
            if Confirm.ask("Use existing profile?", default=True):
                return existing
            console.print()

    if not check_ai_available():
        console.print(
            "[yellow]AI not configured.[/yellow]\n"
            "  Set $AI_API_KEY, $AI_API_URL, and $AI_MODEL, or run with --configure.\n"
            "  You can still enter profile details manually."
        )

    console.print("[bold]How would you like to enter your profile?[/bold]")
    console.print("  1. Enter details manually")
    console.print("  2. Upload a resume PDF")
    console.print("  3. Provide a LinkedIn profile URL")

    source_choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="1")
    profile = None
    source_method = "manual"

    if source_choice == "3":
        source_method = "LinkedIn"
        url = Prompt.ask("LinkedIn profile URL")
        profile = scrape_linkedin_profile(url)
        if profile is None:
            console.print("[yellow]Falling back to manual entry...[/yellow]")
            source_method = "manual"
            profile = manual_profile_entry()
    elif source_choice == "2":
        source_method = "PDF"
        path = Prompt.ask("Path to resume PDF")
        profile = parse_resume_pdf(path)
        if profile is None:
            console.print("[yellow]Falling back to manual entry...[/yellow]")
            source_method = "manual"
            profile = manual_profile_entry()
    else:
        profile = manual_profile_entry()

    if profile is None:
        console.print("[red]Could not build profile. Exiting.[/red]")
        return None

    if source_method in ("LinkedIn", "PDF"):
        supplement_table = Table(box=None, show_header=False, show_edge=False, padding=(0, 2))
        supplement_table.add_column("Field", style="bold")
        supplement_table.add_column("Value")
        supplement_table.add_row("Name", profile.get("name", ""))
        supplement_table.add_row("Title", profile.get("title", "[yellow]Not detected[/yellow]"))
        supplement_table.add_row(
            "Skills",
            f"{len(profile.get('skills', []))} detected: {', '.join(profile.get('skills', []))}"
            if profile.get("skills")
            else "[yellow]None[/yellow]",
        )
        supplement_table.add_row(
            "Experience",
            f"~{profile.get('experience', '')} years"
            if profile.get("experience")
            else "[yellow]Not detected[/yellow]",
        )
        console.print(f"\n[green]Profile loaded from {source_method}:[/green]")
        console.print(supplement_table)
        if Confirm.ask("Does this look correct? You can supplement it.", default=True):
            extra_skills = Prompt.ask(
                "Additional skills (comma-separated, or leave blank)", default=""
            )
            if extra_skills.strip():
                profile["skills"].extend([s.strip() for s in extra_skills.split(",") if s.strip()])
            if not profile.get("title") or not profile["title"].strip():
                if check_ai_available():
                    suggested = ai_suggest_titles(profile.get("skills", []))
                else:
                    suggested = None
                profile["title"] = Prompt.ask(
                    "Your job title", default=suggested[0] if suggested else ""
                )
            if not profile.get("experience") or not str(profile["experience"]).strip():
                profile["experience"] = Prompt.ask("Years of experience", default="")
            if not profile.get("headline"):
                profile["headline"] = Prompt.ask(
                    "Professional headline", default=profile.get("title", "")
                )
        else:
            profile = manual_profile_entry()

    save_profile(profile)
    return profile
