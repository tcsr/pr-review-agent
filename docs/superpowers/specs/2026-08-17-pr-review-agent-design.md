# PR Review Agent — Design Spec

**Date:** 2026-08-17
**Status:** Approved (brainstorming complete)

## 1. Purpose

A standalone, self-hostable service that automates all activities related to
pull-request review across multiple Git platforms (GitHub, Bitbucket, GitLab,
…) using a configurable LLM backend (Claude, OpenAI, or a local model). Runs
anywhere Docker runs — including fully offline on localhost.

## 2. Goals & Non-Goals

### Goals
- Automate 7 review activities on every PR (see §6).
- Be platform-agnostic on two axes: **Git platform** and **LLM provider**.
- Real-time reaction via webhooks, with polling as a firewall-friendly fallback.
- Deploy-anywhere: single container, SQLite by default, no mandatory cloud
  services.
- Fully runnable and testable on localhost, offline, with no accounts.
- Deterministic dedup: never post duplicate reviews for the same commit.

### Non-Goals
- Not a CI system; it does not run the project's test suite. It *checks whether*
  CI/tests exist and pass (via platform status API), but does not execute them.
- Not a merge-bot; it sets review verdicts but does not auto-merge (out of scope
  v1; can be added later).
- No web UI in v1. Configuration is file + env. (A dashboard is a future item.)

## 3. Architecture

```
                    ┌─────────────────────────────┐
   webhook  ─────►  │  Ingress (FastAPI)          │
   (real-time)      │  - /webhook/{platform}      │
                    │  - HMAC signature verify    │
                    └──────────────┬──────────────┘
   poller  ────────────────────────┤  (APScheduler, fallback)
                                    ▼
                    ┌─────────────────────────────┐
                    │  Job Queue (DB-backed)      │  dedup by (repo, PR, sha, task)
                    └──────────────┬──────────────┘
                                   ▼
                    ┌─────────────────────────────┐
                    │  Worker                     │
                    │  1. fetch diff  (GitAdapter)│
                    │  2. run tasks   (Reviewer)  │
                    │  3. post result (GitAdapter)│
                    └──────┬───────────────┬──────┘
                           ▼               ▼
                 GitPlatformAdapter   LLMAdapter
                 (github/bitbucket)   (claude/openai/local)
```

Both provider axes sit behind abstract interfaces; core logic (queue, worker,
reviewer, tasks) never references a concrete provider.

## 4. Components

| Component | Purpose | Depends on |
|-----------|---------|------------|
| `app/main.py` | FastAPI entrypoint, wires everything | config |
| `app/ingress` | Webhook routes, per-platform signature verify, event → job | config, queue |
| `app/poller` | APScheduler job; lists open PRs per repo; enqueues | GitAdapter, queue |
| `app/queue` | enqueue / claim / complete / fail jobs; dedup; retry | store |
| `app/git/base.py` | abstract `GitPlatformAdapter` | — |
| `app/git/github.py`, `bitbucket.py`, `gitlab.py` | concrete impls | httpx |
| `app/git/factory.py` | build adapter from repo config | git/* |
| `app/llm/base.py` | abstract `LLMAdapter` | — |
| `app/llm/claude.py`, `openai.py`, `local.py` | concrete impls | provider SDK / httpx |
| `app/llm/factory.py` | build adapter from config | llm/* |
| `app/reviewer` | orchestrates enabled tasks for a job | LLMAdapter, tasks |
| `app/tasks/*` | one module per activity (§6) | reviewer |
| `app/store` | SQLAlchemy models + session; SQLite/Postgres | — |
| `app/config` | pydantic-settings; env + YAML merge | — |
| `app/redact` | strip secrets/tokens from diffs before LLM | — |

### 4.1 `GitPlatformAdapter` interface

Every platform implements:

- `list_open_prs(repo) -> list[PR]`
- `get_pr_meta(repo, pr) -> PRMeta` (title, body, author, base/head sha, labels,
  linked issues, CI status)
- `get_diff(repo, pr) -> Diff` (per-file patches)
- `get_changed_files(repo, pr) -> list[FileChange]`
- `post_comment(repo, pr, body) -> CommentId`
- `post_inline_comment(repo, pr, path, line, body, side) -> CommentId`
- `set_review_verdict(repo, pr, verdict, body)` (approve / request_changes / comment)
- `add_labels(repo, pr, labels)`
- `assign_reviewers(repo, pr, reviewers)`
- `get_thread(repo, pr) -> list[Comment]`
- `reply(repo, pr, in_reply_to, body)`
- `verify_webhook(headers, raw_body) -> Event | None`

`PR`, `PRMeta`, `Diff`, `FileChange`, `Comment`, `Event` are neutral
dataclasses defined once in `app/git/models.py`; each concrete adapter maps its
platform's API shape into these. Core code only ever sees neutral types.

### 4.2 `LLMAdapter` interface

- `complete(system: str, messages: list[Message], tools: list[Tool] | None,
  max_tokens: int) -> LLMResponse`
- `count_tokens(text) -> int`

`LLMResponse` carries text, optional tool calls, and usage. Tool-calling is used
by `qa_reply` and `triage`; other tasks are plain completions with structured
(JSON) output validated against a schema.

## 5. Data flow (one PR event)

1. **Ingress**: webhook hits `/webhook/{platform}` → adapter `verify_webhook`
   (HMAC / token) → returns neutral `Event` or `None` (reject 401). Poller path
   produces the same `Event` from an API list.
2. **Enqueue**: event → one job per enabled task, keyed
   `(platform, repo, pr#, head_sha, task)`.
3. **Dedup**: if a job with that exact key is already `done` or `in_progress`,
   skip. A new `head_sha` (force-push / new commit) produces fresh jobs.
4. **Claim**: worker atomically claims a `pending` job (row-lock / `UPDATE …
   RETURNING`), so multiple workers never double-process.
5. **Fetch**: `get_pr_meta` + `get_diff` (+ `get_thread` for `qa_reply`).
6. **Redact**: run diff through `app/redact` (strip API keys, tokens, `.env`
   values by regex) before it ever reaches the LLM.
7. **Run task**: task builds prompt, calls `LLMAdapter`, parses/validates output.
8. **Post**: results posted via `GitAdapter`.
9. **Complete**: job → `done`, `head_sha` recorded.

### Error handling
- Transient (HTTP 429/5xx, LLM timeout): retry with exponential backoff, max N
  (config). After max → job `failed` (dead-letter table), logged with context.
- Permanent (401/403/404, malformed): fail immediately, no retry, logged.
- Partial task failure does not fail the whole PR — each task is its own job.
- All external calls time-bounded; worker never blocks indefinitely.

## 6. Review tasks (each a module, toggle per repo)

| Task | Trigger | Output | Git method |
|------|---------|--------|-----------|
| `code_review` | PR opened / synchronized | inline comments per finding (bug, style, security, perf) | `post_inline_comment` |
| `summarize` | PR opened / synchronized | one TL;DR comment (what changed & why) | `post_comment` |
| `suggest_fixes` | PR opened / synchronized | suggestion blocks (platform native suggested-change syntax where supported) | `post_inline_comment` |
| `verdict` | after `code_review` | approve / request_changes with rationale | `set_review_verdict` |
| `compliance` | PR opened / synchronized | checklist comment: tests present? PR desc filled? linked issue? CI green? | `post_comment` |
| `triage` | PR opened | labels (size, area, type) + suggested reviewers | `add_labels`, `assign_reviewers` |
| `qa_reply` | comment created mentioning the bot | threaded reply answering the question | `get_thread`, `reply` |

### Ordering
`verdict` depends on `code_review` output → within a PR sync, `code_review` runs
before `verdict` (task dependency declared in reviewer). Others are independent
and may run concurrently.

### Guardrails
- **Large diffs**: chunk by file; skip generated/vendored/lockfiles by glob
  config; hard cap `max_tokens_per_pr` — if exceeded, review top-N most-changed
  files and post a note that the diff was truncated (no silent truncation).
- **Secret safety**: `app/redact` always runs; `local` LLM option for
  privacy-sensitive repos (nothing leaves the host).
- **Idempotency on re-run**: before posting, `qa_reply`/`summarize`/`compliance`
  update their prior bot comment (by marker) instead of stacking duplicates
  within the same `head_sha`.

## 7. Configuration

Single `config.yaml`; secrets via env interpolation (`${VAR}`).

```yaml
llm:
  provider: claude            # claude | openai | local
  model: claude-sonnet-5
  api_key: ${LLM_API_KEY}
  base_url: null              # set for local (e.g. http://localhost:11434/v1)
  max_tokens_per_pr: 40000
  retry:
    max_attempts: 4
    backoff_seconds: 2

store:
  url: sqlite:///data/agent.db   # or postgresql://user:pass@host/db

ingress:
  enabled: true
  webhook_secret: ${WEBHOOK_SECRET}

poller:
  enabled: true
  interval_seconds: 60

defaults:
  tasks: [code_review, summarize, suggest_fixes, verdict, compliance, triage, qa_reply]
  skip_globs: ["*.lock", "dist/**", "vendor/**", "*.min.js"]

repos:
  - platform: github            # github | bitbucket | gitlab
    full_name: myorg/myrepo
    token: ${GITHUB_TOKEN}
    tasks: null                 # null → inherit defaults; or override list
  - platform: bitbucket
    full_name: myteam/myrepo
    token: ${BITBUCKET_TOKEN}
    tasks: [code_review, summarize]
```

Config validated at startup (pydantic); invalid config → fail fast with a clear
message. Unknown platform/provider → startup error, not runtime crash.

## 8. State store schema (SQLAlchemy)

- `jobs`: id, platform, repo, pr_number, head_sha, task, status
  (pending/in_progress/done/failed), attempts, created_at, updated_at, error.
  Unique index on `(platform, repo, pr_number, head_sha, task)` → dedup.
- `posted_comments`: job_id, external_comment_id, marker → enables idempotent
  update-instead-of-duplicate.
- `dead_letter`: job_id, payload, last_error, failed_at.

SQLite and Postgres share the same models. Migrations via Alembic.

## 9. Deployment

- `Dockerfile` (slim Python base) + `docker-compose.yml` (service + optional
  Postgres profile).
- SQLite volume-mounted at `/data` by default.
- Horizontal scale: set `store.url` to Postgres; run N worker containers — the
  DB-backed queue with atomic claim coordinates them.
- Webhook needs a public URL (reverse proxy / tunnel). Poller covers firewalled
  / private-network installs with no inbound port.

## 10. Local development & testing (localhost-first)

**Level 1 — offline unit/integration (no accounts, no network):**
- `FakeGitAdapter` (in-memory PR, records posted comments) and `FakeLLMAdapter`
  (returns canned/scripted responses).
- In-memory SQLite.
- `pytest` exercises queue, dedup, retry, every task, and reviewer ordering
  with zero network. This is the default dev loop.

**Level 2 — local service with fixture payloads:**
- `uvicorn app.main:app --reload` on `localhost:8000`.
- POST recorded webhook fixtures:
  `curl -X POST localhost:8000/webhook/github -d @tests/fixtures/pr_opened.json`.
- Full pipeline runs against `FakeLLMAdapter` or `local` LLM. No internet.

**Level 3 — local against a real repo (optional):**
- `local` LLM provider pointing at Ollama on `localhost` → no API key, no cloud.
- Poller mode → no public URL needed; polls a real repo from the dev machine.
- Webhook mode → `cloudflared`/`ngrok` tunnel exposes `localhost:8000` only when
  testing live webhooks.

### Test strategy
- **Unit**: each concrete GitAdapter maps recorded API JSON fixtures → neutral
  types (no live calls).
- **Contract**: recorded-fixture tests per platform adapter (vcr-style).
- **Integration**: full event→post flow with FakeLLM + SQLite in-memory.
- **TDD** throughout (test before implementation).

## 11. Milestones (implementation order)

1. Skeleton: config, store, neutral models, `FakeGitAdapter`, `FakeLLMAdapter`,
   queue + dedup — all tested offline.
2. Reviewer + `code_review` + `summarize` tasks against fakes.
3. Remaining 5 tasks against fakes.
4. Real GitHub adapter (contract-tested).
5. Claude + OpenAI + local LLM adapters.
6. Ingress (webhooks + signature verify) and poller.
7. Bitbucket + GitLab adapters.
8. Dockerfile, compose, Alembic migrations, docs.

## 12. Open questions / future

- Auto-merge on approval (deferred).
- Web dashboard for status/metrics (deferred).
- Per-org custom review rulepacks / prompt overrides (deferred, but prompt
  templates are files from day one to allow this later).
