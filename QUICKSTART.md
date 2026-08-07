# Matcha — 5-Command Quickstart 🍵

Matcha is a multi-source job aggregator with AI-powered relevance ranking.
Enter your profile once, get ranked matches from LinkedIn, Indeed, Naukri,
RemoteOK, and web search. You only need **five commands** to go from zero to
searching.

> Full reference: [`README.md`](README.md)

---

## 1. Install

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .
```

That's it — the `matcha` console script is installed into the venv. No
environment variables are required to install or run.

## 2. Create your profile & run your first search

```bash
venv/bin/matcha
```

The first run asks how you want to enter your profile — **PDF resume**,
**LinkedIn URL**, or **manual entry** — then asks for a search query,
location (blank = remote), and how many days back to look.

- Your profile is saved to `~/.matcha/profile.json` and reused on later runs
- Results open in an interactive TUI: `↑↓` navigate · `Enter` details · `s`
  save · `o` open in browser · `n`/`p` page · `l` saved jobs · `r` re-run ·
  `q` quit

## 3. Turn on AI matching (recommended)

Set your API key — the single switch that enables AI:

```bash
export MINIMAX="your-api-key"     # put this in your shell profile (~/.zshrc)
venv/bin/matcha
```

…or run the interactive wizard (stores the key in your OS keyring, never
plaintext):

```bash
venv/bin/matcha --configure
```

Optional: `AI_PROVIDER` (default `kilo`), `AI_API_URL`, `AI_MODEL`,
`AI_MODEL_FAST` — see the README's [Environment Variables](README.md#environment-variables).
Without a key, Matcha still works — it just ranks heuristically.

## 4. Verify everything is healthy

```bash
venv/bin/matcha doctor            # per-source health + active backends
venv/bin/matcha doctor --json     # machine-readable
```

`ok` on the zero-config sources (RemoteOK, Naukri, Web Search, …) **plus an
`ok` on the AI matching line** means you're fully wired. The AI line shows
provider, best/fast models, and whether a key is set — `off` = heuristic-
only, `warn` = partial setup (e.g. a key with no provider).

## 5. Run headless (scripts / agents / cron)

```bash
venv/bin/matcha search -q "Platform Engineer" -l Pune -d 7 --json
venv/bin/matcha watch -q "Platform Engineer" -l Pune -d 7 --json   # only NEW jobs
```

Both need a saved profile (run `matcha` once first). `watch` writes
`~/.matcha/latest.json` and tracks new-vs-seen jobs.

---

## Agents (Claude / OpenCode / MCP)

Want an agent to drive Matcha for you? Install the bundled skill once:

```bash
venv/bin/matcha skill --install   # → ~/.agents/skills/matcha + ~/.claude/skills/matcha
```

The skill knows the whole workflow — health check (`matcha doctor --json`,
including the AI availability check), ranked `search`, and new-job `watch`
— and points agents back to this quickstart. The optional MCP server
(`pip install -e '.[agent]'` then `matcha mcp`) exposes the same tools
(`matcha_status`, `matcha_search`) to MCP clients.

---

## Good to know

- **No API keys required** for core search — AI and Google Jobs (SerpAPI)
  are optional upgrades.
- **All state lives in `~/.matcha/`** — profile, config, saved jobs, logs.
- **Need to start over?** `venv/bin/matcha --new-profile`
- **Automate without prompts:** `venv/bin/matcha --non-interactive`

Dive deeper — data sources, filters, ranking, saved jobs, RSS, circuit
breakers, and the agent surface — in [`README.md`](README.md).
