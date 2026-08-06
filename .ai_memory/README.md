# AI Memory Bank — How to Use

This folder is the **persistent brain** of **Matcha**, a personal India-focused
job-search CLI (Python TUI, multi-source scraping, AI-assisted ranking). AI
assistants (Freebuff primary, OpenCode optional) are stateless — they forget
everything when the session ends. This folder makes project state survive by
storing it in plain markdown that any session can read and update.

**Rule of thumb:** the repo (code + this folder) is the source of truth. A
session's chat history is disposable. When memory conflicts with code, the code
wins — then fix the memory file.

> ⚠️ Note: there is **no `AGENTS.md`** in this repo. `.ai_memory/` is the sole
> memory layer. The Matcha 2.0 rebuild plan lives in `revamp/` — see
> `revamp/matcha-2.0-strategy.md` (the source of truth for all next steps) and
> `revamp/phase-0-handoff-prompt.txt` (ready-made prompt to start Phase 0).

## The files

| File | Role | Who writes it |
|---|---|---|
| `README.md` | This guide | — |
| `SYSTEM_CONTEXT.md` | Structural anchor: mission, constraints, stack, AI rules, directory map | Primary assistant, rarely |
| `system_state.md` | What has been built (checkboxes) + the 2.0 Phase 0-7 roadmap | Updated when a milestone flips |
| `active_task.md` | What is being worked on right now + next steps | Updated at the start of each step |
| `session_log.md` | Append-only activity journal (crash-safe write-ahead log) | Appended after every completed step |
| `architectural_decisions.md` | ADRs — why decisions were made | New ADR when a significant decision lands |

## Daily workflow

### 1. Start a session (load memory)
Open Freebuff (or OpenCode) and paste:

> Read `.ai_memory/` (start with `SYSTEM_CONTEXT.md` and `active_task.md`).
> Check git status/diff and the session_log.md tail for anything done since the
> last sync. What's our status and next step?

The assistant loads the last known-good state, detects anything uncommitted or
unrecorded, and resumes exactly where you left off. For Matcha 2.0 work, the
strategy doc (`revamp/matcha-2.0-strategy.md`, all 23 sections) is mandatory
reading before writing code.

### 2. While working (sync continuously)
- Completed a step? Ask the assistant to **append a line to `session_log.md`**.
- Starting a new task? Ask it to **update `active_task.md`** (what you're doing now).
- Finished a milestone? Ask it to **tick the checkbox in `system_state.md`**.
- Made a significant decision? Ask it to **write an ADR** in `architectural_decisions.md`.

### 3. End a session (sync + commit)
1. Ask: *"Sync memory: update `system_state.md`, `active_task.md`, and `session_log.md` for everything we did."*
2. Commit — the commit is what makes recovery deterministic (ADR 10):

```bash
git add -A && git commit -m "docs: memory sync — <what changed>"
```

## Crash recovery (when a session dies without syncing)

Context limit, daily cap, crash, closed tab — if the final sync never happened:

1. **Don't panic.** Work on disk is never lost. Only the *summary* may be stale.
2. Open a new session with the startup prompt (workflow §1). It will:
   - read the memory files (last known-good state),
   - run `git status` / `git diff` to see what changed since the last commit,
   - read the `session_log.md` tail for the raw activity trail,
   - reconcile memory with what the disk actually shows, then resume.
3. If it reports a stale next-step, have it re-derive from git + the journal.

## Verify it works (30-second test)

1. Close the current chat. Open a **new** Freebuff session.
2. Paste the startup prompt (workflow §1).
3. It should reconstruct: **Matcha 1.x complete; Matcha 2.0 planning done;
   next = get user's go-ahead, then start Phase 0** (src/ layout, errors.py,
   probe.py, doctor.py, sources/ registry — per `revamp/phase-0-handoff-prompt.txt`).
   If it says anything materially different, that's a protocol bug — report it
   and fix the design.

## Do's and Don'ts

- ✅ Sync per step, not per session.
- ✅ Commit at the end of every working session.
- ✅ Append to `session_log.md` — never rewrite it.
- ✅ Let the assistant read files from disk instead of relying on chat memory.
- ✅ Read the revamp strategy doc before implementing 2.0 work.
- ❌ Don't hold important decisions only in conversation.
- ❌ Don't trust memory files over the actual code — when they conflict, the code wins; then fix the memory file.
