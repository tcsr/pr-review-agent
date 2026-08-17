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

## Next slices
Webhooks + poller, rules/stack packs, additional platforms (Bitbucket/GitLab), and the admin UI — see docs/superpowers/specs.
