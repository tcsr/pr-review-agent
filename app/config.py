from __future__ import annotations

import os
import re
from pydantic import BaseModel, ValidationError
import yaml

from app.models import Platform

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


class RepoConfig(BaseModel):
    platform: Platform
    full_name: str
    token: str
    tasks: list[str] | None = None


class LLMConfig(BaseModel):
    provider: str = "fake"
    model: str = "fake"
    api_key: str = ""
    base_url: str | None = None
    max_tokens_per_pr: int = 40000


class StoreConfig(BaseModel):
    url: str = "sqlite:///data/agent.db"


class Settings(BaseModel):
    llm: LLMConfig
    store: StoreConfig
    defaults_tasks: list[str]
    repos: list[RepoConfig]


def _interpolate(obj, env: dict):
    if isinstance(obj, str):
        def repl(m):
            name = m.group(1)
            if name not in env:
                raise ValueError(f"Missing environment variable: {name}")
            return env[name]
        return _VAR.sub(repl, obj)
    if isinstance(obj, list):
        return [_interpolate(x, env) for x in obj]
    if isinstance(obj, dict):
        return {k: _interpolate(v, env) for k, v in obj.items()}
    return obj


def load_settings(path: str | None = None, env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    path = path or "config.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    raw = _interpolate(raw, env)
    try:
        return Settings(
            llm=LLMConfig(**raw.get("llm", {})),
            store=StoreConfig(**raw.get("store", {})),
            defaults_tasks=raw["defaults"]["tasks"],
            repos=[RepoConfig(**r) for r in raw.get("repos", [])],
        )
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}") from e
