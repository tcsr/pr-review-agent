# PR Review Agent

Standalone, self-hostable, multi-platform PR review agent.

## Foundation status
Offline core: config, state store, neutral models, fake adapters, job queue with
dedup, and the reviewer running `code_review` + `summarize`. No network required.

## Dev setup
    pip install -e ".[dev]"
    pytest -v

All tests run fully offline against fake Git and LLM adapters.

## Next slices
Real GitHub/Bitbucket/GitLab adapters, Claude/OpenAI/local LLMs, webhooks +
poller, rules/stack packs, and the admin UI — see docs/superpowers/specs.
