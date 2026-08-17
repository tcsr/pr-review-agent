# PR Review Agent

Standalone, self-hostable, multi-platform PR review agent.

## Foundation status
Offline core: config, state store, neutral models, fake adapters, job queue with
dedup, and the reviewer running `code_review` + `summarize`. No network required.

## Dev setup
    pip install -e ".[dev]"
    pytest -v

All tests run fully offline against fake Git and LLM adapters.

## Real adapters (slice 2)
GitHub platform adapter and Claude/OpenAI/local LLM adapters are implemented
over httpx and selected via config (see `config.example.yaml`). All adapter
tests run offline using `httpx.MockTransport` — no live API calls.

    cp config.example.yaml config.yaml   # then set env vars

GitHub auth uses a Bearer token (works with fine-grained and classic personal access tokens on api.github.com).

Providers: `claude` (Anthropic /v1/messages), `openai` (/v1/chat/completions),
`local` (OpenAI-compatible endpoint like Ollama), `fake` (offline default).

## Running the service (slice 3)
The agent runs autonomously: a worker drains the job queue, a FastAPI webhook
ingress enqueues jobs from GitHub PR events, and a poller sweeps open PRs on an
interval as a fallback.

    cp config.example.yaml config.yaml    # set env vars first
    python -m app.main                    # serves on :8000, starts worker + poller

- `POST /webhook/github` — point a GitHub webhook here (content-type JSON,
  secret = `ingress.webhook_secret`); PR `opened`/`synchronize`/`reopened`
  events enqueue review jobs.
- `GET /health` — liveness.
- Poller runs every `poller.interval_seconds` when `poller.enabled`.

All ingress/worker/poller logic is tested offline (FastAPI TestClient +
httpx.MockTransport); no network in the test suite.

## Rules & stacks (slice 4)
Reviews are shaped by config:
- **Gates** (deterministic, `block`|`warn`): `require_linked_issue`,
  `require_pr_description`, `max_changed_files`, `require_tests_for`,
  `title_regex`, `ci_must_pass`. The `compliance` task posts a checklist.
- **Review criteria** (natural language) are injected into the `code_review`
  prompt.
- **Stack packs** auto-apply when a stack is detected from changed files
  (Angular, React, Next, NestJS, Node, Java, Python, JS, TS, CSS); disable one
  with `stacks.packs: {angular: false}`.

Configure under top-level `rules:`/`stacks:` (global) or per-repo `rules:`/
`stacks:` (repo overrides global). See `config.example.yaml`.

## Task roster (slice 5)
All review tasks now available (enable per repo via `tasks:` / `defaults.tasks`):
- `code_review` — inline findings
- `suggest_fixes` — inline GitHub suggestion blocks
- `summarize` — PR summary comment
- `compliance` — gate checklist
- `triage` — size/type labels
- `verdict` — approve / request_changes (a failed `block` gate forces
  request_changes without calling the LLM)

Diffs are secret-redacted before any content is sent to an LLM.

## Q&A replies (slice 6)
Mention the bot in a PR comment (e.g. `@pr-agent why this change?`) and it
replies in the thread, using the diff as context. Set the handle with
top-level `bot_handle:` in config; an empty handle disables the comment path.
Point a GitHub `issue_comment` webhook at `/webhook/github` (same endpoint).
Comment events enqueue only the `qa_reply` task, and only when the bot is
mentioned.

## Next slices
Additional platforms (Bitbucket/GitLab), the admin UI, and deferred tasks
— see docs/superpowers/specs.
