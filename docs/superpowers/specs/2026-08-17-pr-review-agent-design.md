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
- Bundled optional admin UI for dashboard, config, and job management (§6c).

### Non-Goals
- Not a CI system; it does not run the project's test suite. It *checks whether*
  CI/tests exist and pass (via platform status API), but does not execute them.
- Not a merge-bot; it sets review verdicts but does not auto-merge (out of scope
  v1; can be added later).
- No multi-user auth / RBAC in v1 (single admin only; §6c).

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
| `app/rules` | load + evaluate deterministic gates and NL review criteria; merge by precedence | store, GitAdapter |
| `app/stack_detect` | infer stacks from changed files + manifests | git/models |
| `app/packs` | built-in per-stack rulepacks (criteria/prompt files) + loader | rules |
| `app/ui` | server-rendered admin UI (FastAPI + Jinja/HTMX + Tailwind) | store, config, queue |
| `app/api` | JSON endpoints backing the UI (and future SPA/CLI) | store, queue |
| `app/auth` | single-admin auth (session cookie), guards UI + API | config |

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

## 6a. PR rules & criteria

Two kinds of rules, both supported.

### A. Deterministic gates (`app/rules`, no LLM)
Code-evaluated checks against PR metadata/diff. Cheap, reliable. Each gate has a
`severity`: `block` | `warn`.
- `block` → forces `verdict=request_changes`, overriding the LLM's approve; the
  reason is posted.
- `warn` → posted in the `compliance` checklist, does not change verdict.

Built-in gates: `require_linked_issue`, `require_pr_description`,
`max_changed_files`, `max_changed_lines`, `require_tests_for` (glob → require a
matching test change), `title_regex` (e.g. conventional commits),
`branch_regex`, `ci_must_pass`.

### B. LLM review criteria (natural language)
A list of NL rules injected into the `code_review`/`suggest_fixes` prompts, plus
optional full `prompt_overrides` per task. Teams express house style, security
conventions, etc.

### Rule sources & precedence (highest wins)
1. **Target repo `.pr-agent.yaml`** (committed in the reviewed repo) — each team
   owns its rules; fetched from the PR's base ref at review time.
2. **Server per-repo config** (`repos[].rules`).
3. **Auto-loaded stack rulepacks** (§6b).
4. **Global defaults** (`rules:` at top level).

Merge is per-key deep-merge; lists append unless a key is explicitly set to
replace. Missing `.pr-agent.yaml` is fine → fall through to server/global.

## 6b. Multi-stack support

The LLM reviews any language out of the box. Stack awareness sharpens it.

### Detection (`app/stack_detect`)
Infer the set of stacks for a PR from:
- changed file extensions (`.tsx`, `.java`, `.py`, `.scss`, …)
- manifest / signal files: `package.json` deps (Angular vs React vs Next vs
  NestJS), `angular.json`, `next.config.js`, `nest-cli.json`, `pom.xml` /
  `build.gradle` (Java), `pyproject.toml` / `requirements.txt` (Python).

A PR may resolve to multiple stacks (e.g. NestJS API + Angular UI); each
detected stack's pack is loaded.

### Built-in rulepacks (`app/packs`)
One criteria/prompt file per stack, auto-injected when detected. Ship v1 packs
for: Angular, React, Next.js, NestJS, Node, Java, Python, JavaScript/TypeScript,
CSS/SCSS. Examples:

| Stack | Sample built-in criteria |
|-------|--------------------------|
| Angular | `OnPush` detection, unsubscribe/`takeUntil` leaks, no template logic, DI |
| React | hook dep arrays, no inline-object props, `key` props, no direct DOM |
| Next.js | server/client component boundaries, `use client` misuse, data fetching |
| NestJS | DTO validation, module boundaries, injectable scope, guards/pipes |
| Node | async error handling, no sync-blocking calls, stream handling |
| Java | null safety, try-with-resources, thread safety, exception hygiene |
| Python | type hints, PEP8, context managers, mutable default args |
| CSS/SCSS | specificity, `!important` abuse, responsive units |

Teams override or disable any pack (see config). Packs are plain files, so new
stacks are added without code changes.

## 6c. Admin UI

Server-rendered, bundled in the same container (no separate Node build) — keeps
the "single container, deploy anywhere" property. Stack: FastAPI + Jinja2 +
HTMX + Tailwind (CDN or prebuilt CSS). Backed by `app/api` JSON endpoints so a
React SPA or CLI can be added later without rework.

### Screens
- **Dashboard** — repos, recent PRs reviewed, job counts by status, dead-letter
  count, LLM cost today.
- **PR detail** — per-PR: detected stacks, task results, what was posted, gate
  pass/fail, token usage, **re-run** button (enqueues fresh jobs for head_sha).
- **Repos** — add/remove repo, set platform + token, toggle tasks, choose LLM
  override per repo.
- **Rules** — edit global gates (enable, severity block/warn) and NL criteria;
  enable/disable stack packs. Writes back to config store.
- **Jobs** — live queue + dead-letter, retry a failed job.
- **Settings** — LLM provider/model, poller interval, change admin password.

### Auth (`app/auth`)
Single-admin, session-cookie login. Credentials from env
(`ADMIN_USER` / `ADMIN_PASSWORD_HASH`). All UI routes and mutating API routes
require the session; webhook routes are exempt (own HMAC verify). No multi-user
system in v1 (deferred). Passwords hashed (argon2/bcrypt); cookie is httponly +
secure.

### Notes
- UI is optional: `ui.enabled: false` runs the service headless (config-file
  only), preserving the pure-backend deploy.
- Config edits made in the UI persist to the store and are reconciled with
  `config.yaml` on startup (file is the seed; DB is the live source once running).

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

ui:
  enabled: true
  admin_user: ${ADMIN_USER}
  admin_password_hash: ${ADMIN_PASSWORD_HASH}   # argon2/bcrypt hash

defaults:
  tasks: [code_review, summarize, suggest_fixes, verdict, compliance, triage, qa_reply]
  skip_globs: ["*.lock", "dist/**", "vendor/**", "*.min.js"]

stacks:
  auto_detect: true
  packs:                        # optional; omit → use built-ins
    react: ./packs/react.md     # override a built-in pack
    angular: off                # disable a built-in pack

rules:                          # global defaults; repo .pr-agent.yaml overrides
  gates:
    require_linked_issue: { enabled: true,  severity: warn }
    require_pr_description: { enabled: true, severity: warn }
    max_changed_files: { value: 50, severity: warn }
    require_tests_for: { globs: ["src/**"], severity: block }
    title_regex: { pattern: "^(feat|fix|chore|docs)(\\(.+\\))?: ", severity: block }
    ci_must_pass: { enabled: true, severity: block }
  review_criteria:
    - "No leftover debug prints/console.log."
    - "New public functions need docstrings."
    - "No secrets or hardcoded credentials."
  prompt_overrides:
    code_review: null           # or ./prompts/custom_review.md

repos:
  - platform: github            # github | bitbucket | gitlab
    full_name: myorg/myrepo
    token: ${GITHUB_TOKEN}
    tasks: null                 # null → inherit defaults; or override list
    rules: null                 # null → inherit; or per-repo override block
  - platform: bitbucket
    full_name: myteam/myrepo
    token: ${BITBUCKET_TOKEN}
    tasks: [code_review, summarize]
```

Each reviewed repo may also commit a `.pr-agent.yaml` at its root (same `rules`/
`stacks` shape) which takes precedence over server config (§6a).

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
3. Rules engine (deterministic gates + NL criteria) + precedence merge, tested
   offline.
4. Stack detection + built-in rulepacks; pack auto-injection into prompts.
5. Remaining 5 tasks against fakes.
6. Real GitHub adapter (contract-tested), incl. `.pr-agent.yaml` fetch.
7. Claude + OpenAI + local LLM adapters.
8. Ingress (webhooks + signature verify) and poller.
9. Bitbucket + GitLab adapters.
10. `app/api` JSON endpoints + `app/auth` single-admin login.
11. Admin UI (dashboard, PR detail, repos, rules, jobs, settings).
12. Dockerfile, compose, Alembic migrations, docs.
13. (Future) Optional native-linter integration (eslint/ruff/checkstyle/…).

## 12. Open questions / future

- Auto-merge on approval (deferred).
- Web dashboard for status/metrics (deferred).
- Native-linter integration as ground-truth for the LLM (deferred, milestone 13).
- Multi-user auth / RBAC and optional React SPA on top of `app/api` (deferred).
- Rulepack marketplace / sharing across orgs (deferred; packs are files, so this
  is additive later).
