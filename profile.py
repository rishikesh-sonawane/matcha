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

from ai import ai_extract_profile, check_ai_available
from config import load_profile, save_profile

console = Console()


SKILL_TO_TITLE_MAP: list[tuple[set[str], str]] = [
    ({"python", "django", "flask", "fastapi", "sql", "postgresql", "mysql"}, "Backend Developer"),
    (
        {"python", "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy"},
        "Machine Learning Engineer",
    ),
    ({"python", "tensorflow", "pytorch", "opencv"}, "AI Engineer"),
    ({"python", "data", "analyst", "tableau", "power bi", "sql"}, "Data Analyst"),
    ({"python", "spark", "kafka", "hadoop", "airflow", "sql", "pandas"}, "Data Engineer"),
    ({"python", "aws", "docker", "kubernetes", "terraform", "linux", "ci/cd"}, "DevOps Engineer"),
    ({"python", "aws", "azure", "gcp", "docker", "kubernetes"}, "Cloud Engineer"),
    (
        {"javascript", "typescript", "react", "angular", "vue", "node", "nodejs"},
        "Frontend Developer",
    ),
    (
        {"javascript", "typescript", "react", "node", "nodejs", "python", "django"},
        "Full Stack Developer",
    ),
    ({"java", "spring", "hibernate", "microservices"}, "Java Developer"),
    ({"go", "golang", "docker", "kubernetes", "microservices"}, "Go Developer"),
    ({"rust", "systems", "performance"}, "Systems Engineer"),
    ({"sql", "etl", "data", "warehouse", "analytics"}, "Data Engineer"),
    ({"aws", "azure", "gcp", "cloud", "infrastructure"}, "Cloud Engineer"),
    ({"docker", "kubernetes", "helm", "terraform", "ansible", "ci/cd"}, "DevOps Engineer"),
    ({"product", "management", "agile", "scrum", "jira", "confluence"}, "Product Manager"),
    ({"javascript", "react", "html", "css", "frontend", "ui", "ux"}, "Frontend Developer"),
]


def suggest_title(skills: list[str]) -> Optional[str]:
    skill_set = {s.lower() for s in skills}
    best_match = None
    best_count = 0
    for required, title in SKILL_TO_TITLE_MAP:
        count = len(required & skill_set)
        if count > best_count and count >= len(required) * 0.6:
            best_count = count
            best_match = title
    return best_match


def extract_experience(text_lower: str) -> Optional[int]:
    years = re.findall(
        r"(\d+)\s*(?:years?|yrs?|yr)\s*(?:of)?\s*(?:experience|exp|work)?", text_lower
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
        console.print("[red]Could not extract text from PDF. It may be scanned/image-based.[/red]")
        return None

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text_lower = text.lower()

    name = lines[0] if lines else ""

    title_patterns = [
        r"(?:^|\n)\s*(software\s*(?:engineer|developer|architect)|senior\s+software|full.?stack|frontend|backend|devops|data\s*(?:scientist|engineer|analyst)|machine\s+learning|ai\s*engineer|product\s*manager|engineering\s*manager|sre|site\s*reliability|cloud\s*engineer|systems\s*engineer|staff\s*engineer|principal\s*engineer)",
    ]
    title = ""
    for p in title_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            break

    tech_keywords = [
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "golang",
        "rust",
        "c\\+\\+",
        "c#",
        "react",
        "angular",
        "vue",
        "node",
        "nodejs",
        "django",
        "flask",
        "fastapi",
        "spring",
        "aws",
        "azure",
        "gcp",
        "docker",
        "kubernetes",
        "terraform",
        "ansible",
        "sql",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "kafka",
        "rabbitmq",
        "git",
        "linux",
        "ci/cd",
        "jenkins",
        "github actions",
        "gitlab ci",
        "tensorflow",
        "pytorch",
        "scikit-learn",
        "pandas",
        "numpy",
        "graphql",
        "rest",
        "grpc",
        "html",
        "css",
        "sass",
        "agile",
        "scrum",
        "jira",
        "confluence",
        "microservices",
        "kubernetes",
        "helm",
        "opencv",
        "nlp",
        "tableau",
        "power bi",
        "etl",
        "hadoop",
        "spark",
        "airflow",
    ]

    found_keywords = set()
    for kw in tech_keywords:
        if re.search(r"\b" + kw + r"\b", text_lower):
            found_keywords.add(kw.replace("\\+\\+", "++").replace("\\+", "+").replace("\\/", "/"))

    skills = sorted(found_keywords)

    experience_years = extract_experience(text_lower)

    suggested = suggest_title(skills) if not title else None

    summary = text[:500].strip()

    profile = {
        "name": name,
        "title": title.capitalize() if title else "",
        "headline": title.capitalize() if title else "",
        "skills": skills,
        "experience": str(experience_years) if experience_years else "",
        "summary": summary,
    }

    if check_ai_available():
        console.print("[dim]Enhancing profile with AI...[/dim]")
        ai_profile = ai_extract_profile(text[:4000])
        if ai_profile:
            if not profile["title"] and ai_profile.get("title"):
                profile["title"] = ai_profile["title"]
            if not profile["headline"] and ai_profile.get("headline"):
                profile["headline"] = ai_profile["headline"]
            if not profile["experience"] and ai_profile.get("experience"):
                profile["experience"] = ai_profile["experience"]
            ai_skills = ai_profile.get("skills", [])
            existing_skills = set(s.lower() for s in profile["skills"])
            new_skills = [s for s in ai_skills if s.lower() not in existing_skills]
            if new_skills:
                profile["skills"].extend(new_skills)
            profile["summary"] = ai_profile.get("summary", "") or profile["summary"]
            console.print("[green]  AI-enhanced: title/experience/skills enriched[/green]")

    table = Table(box=None, show_header=False, show_edge=False, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Name", name)
    table.add_row(
        "Title",
        profile["title"]
        if profile["title"]
        else f"[yellow]Not detected{' → Suggested: ' + suggested if suggested else ''}[/yellow]",
    )
    table.add_row(
        "Skills",
        f"{len(profile['skills'])} detected: {', '.join(profile['skills'][:10])}{'...' if len(profile['skills']) > 10 else ''}"
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
    title = title_el.get_text(strip=True)
    snippet = snippet_el.get_text(strip=True) if snippet_el else ""

    name = title.split(" - ")[0].strip() if " - " in title else username
    headline = ""

    if " - " in title and " | " in title:
        headline = title.split(" | ")[0].split(" - ", 1)[-1].strip()

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

    tech_keywords = [
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
        "c++",
        "react",
        "angular",
        "vue",
        "node",
        "django",
        "flask",
        "spring",
        "aws",
        "azure",
        "gcp",
        "docker",
        "kubernetes",
        "terraform",
        "sql",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "kafka",
        "git",
        "linux",
        "jenkins",
        "tensorflow",
        "pytorch",
        "graphql",
        "html",
        "css",
        "devops",
        "cloud",
        "sre",
    ]
    snippet_lower = snippet.lower()
    skills = [kw.title() for kw in tech_keywords if kw in snippet_lower]

    return {
        "name": name,
        "headline": headline,
        "skills": skills,
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
            f"{len(profile.get('skills', []))} detected: {', '.join(profile.get('skills', [])[:10])}{'...' if len(profile.get('skills', [])) > 10 else ''}"
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
                suggested = suggest_title(profile.get("skills", []))
                profile["title"] = Prompt.ask(
                    "Your job title", default=suggested or profile.get("headline", "")
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
