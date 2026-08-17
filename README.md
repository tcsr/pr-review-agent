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

## Next slices
Webhooks + poller, rules/stack packs, additional platforms (Bitbucket/GitLab), and the admin UI — see docs/superpowers/specs.
