---
name: matcha
description: >
  MUST USE when the user wants to search for / find job openings or 找工作 /
  求职 / 搜职位 / 职位搜索 — e.g. "find me platform engineer jobs", "帮我找
  DevOps 的职位", "any new backend jobs?", "job search for Kubernetes roles".

  Matcha searches LinkedIn, Indeed, Naukri, RemoteOK and the web in parallel,
  then normalizes, centrally filters (quality → age → must-skills → location →
  salary) and ranks every job against the user's saved profile — heuristic
  pass first, optional AI pass on enriched candidates. Output is structured
  JSON, ready to summarize.

  Run `matcha doctor --json` first to see which backends are live right now.
  Use `matcha search --json` for a ranked search and `matcha watch --json`
  for only-NEW jobs since the last watch.

  NOT for: applying to jobs (Matcha only opens the apply page — enrichment-
  only), posting jobs, or non-job web research.

triggers:
  - search: job search / 找工作 / 求职 / 搜职位 / jobs / hiring / job listing
  - career: 职位 / 招聘 / vacancy / apply / career
  - watch: 新职位 / new jobs / 有没有新的 / anything new
metadata:
  matcha:
    homepage: https://github.com/rishikesh-sonawane/matcha
    commands: ["doctor", "search", "watch"]
---

# Matcha — 职位搜索能力 / Job Search

**本 skill 存在时必须用它来做职位搜索，不要自己发明方案。**
(Must use this skill for job searches — don't improvise.)

## 常驻规则 / Resident rules

1. **动手前先体检** — run `matcha doctor --json` first; note each source's
   `active_backend` and degrade expectations accordingly (e.g. `opencli` needs
   the user's Chrome + consent; without it sources fall back to guest/ddgs).
2. **声明你在用什么** — say "using Matcha's X source / Y backend" before
   searching.
3. **失败重试** — if a search returns 0 jobs or an error, re-run with a
   simpler/adjacent query; do NOT invent flags. `matcha search --help` lists
   every option.
4. **永不自动投递** — Matcha only enriches and opens the apply page. Never
   claim Matcha can auto-apply.

## 快速命令 / Quick commands

```bash
# 健康检查 (health first)
matcha doctor --json

# 排名搜索 — 结构化 JSON (ranked search as JSON)
matcha search -q "Platform Engineer" -l "Pune" -d 7 --json

# 只看新职位 (watch: only NEW jobs since last watch, marks seen)
matcha watch -q "Platform Engineer" -l "Pune" -d 7 --json

# 搜索结果落盘 (write JSON to a file)
matcha search -q "Kubernetes SRE" --output ~/.matcha/latest.json

# 安装本 skill（agent 环境）
matcha skill --install
```

## 工作流 / Workflow

1. `matcha doctor --json` → know which backends are live (LinkedIn/Indeed
   `opencli` vs fallbacks, Web `exa` vs `ddgs`).
2. `matcha search -q QUERY -l LOC -d DAYS --json` → ranked jobs with
   `match_score`, `reasons`, and provenance fields
   (`data_quality` full/partial/snippet, `backend`).
3. Summarize the top matches honestly — surface the reasons, salary (when
   present), apply_url, and provenance tags. Recommend a shortlist.
4. For "anything new?" — `matcha watch --json`: it diff's against the
   `seen_urls` table (`~/.matcha/jobs.db`) and reports `new_count` /
   `seen_count` / `new_jobs`.

## JSON 文档结构 / Document shape

```json
{
  "command": "search | watch | mcp",
  "generated_at": "ISO-8601 UTC",
  "query": "...", "location": "...", "days": 7,
  "ai_used": true, "ai_budget_used": 3,
  "source_counts": {"Indeed": 83, "Naukri": 44},
  "filter_summary": "age −142 · must −21",
  "enriched_count": 12,
  "jobs": [
    {
      "match_score": 86.2,
      "reasons": ["Job title matches profile: platform, engineer", "..."],
      "title": "...", "company": "...", "url": "...", "apply_url": "...",
      "salary": "₹28–40L", "location": "Pune, India", "source": "Indeed",
      "data_quality": "full", "backend": "opencli",
      "listed": "3 days ago", "listed_epoch": 1754...
    }
  ]
}
```

`watch` adds `new_count` / `seen_count` / `new_jobs` (subset of `jobs`).

## 工作区规则 / Workspace rules

- **不要在 agent workspace 创建文件** — use `/tmp/` for scratch and
  `~/.matcha/` for persistent outputs (`latest.json`).
- Reading full job descriptions: `job.description` is in the JSON; for more,
  open `job.apply_url` (or `job.url`) — do not re-scrape from scratch.
