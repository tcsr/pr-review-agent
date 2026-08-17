from __future__ import annotations

import os
import re
from pydantic import BaseModel, ValidationError
import yaml

from app.models import Platform

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


class GateConfig(BaseModel):
    enabled: bool = True
    severity: str = "warn"
    value: int | None = None
    globs: list[str] | None = None
    pattern: str | None = None


class RulesConfig(BaseModel):
    gates: dict[str, GateConfig] = {}
    review_criteria: list[str] = []
    prompt_overrides: dict[str, str] = {}


class StacksConfig(BaseModel):
    auto_detect: bool = True
    packs: dict[str, bool] = {}


class RepoConfig(BaseModel):
    platform: Platform
    full_name: str
    token: str
    tasks: list[str] | None = None
    rules: RulesConfig | None = None
    stacks: StacksConfig | None = None


class LLMConfig(BaseModel):
    provider: str = "fake"
    model: str = "fake"
    api_key: str = ""
    base_url: str | None = None
    max_tokens_per_pr: int = 40000


class StoreConfig(BaseModel):
    url: str = "sqlite:///data/agent.db"


class IngressConfig(BaseModel):
    enabled: bool = True
    webhook_secret: str = ""


class PollerConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 60


class Settings(BaseModel):
    llm: LLMConfig
    store: StoreConfig
    defaults_tasks: list[str]
    repos: list[RepoConfig]
    ingress: IngressConfig = IngressConfig()
    poller: PollerConfig = PollerConfig()
    rules: RulesConfig = RulesConfig()
    stacks: StacksConfig = StacksConfig()
    bot_handle: str = ""


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


def find_repo(settings: "Settings", platform: str, full_name: str) -> RepoConfig | None:
    for r in settings.repos:
        if r.platform.value == platform and r.full_name == full_name:
            return r
    return None


def resolve_tasks(settings: "Settings", repo_cfg: RepoConfig) -> list[str]:
    return repo_cfg.tasks if repo_cfg.tasks is not None else settings.defaults_tasks


def resolve_rules(settings: "Settings", repo_cfg: RepoConfig) -> RulesConfig:
    return repo_cfg.rules if repo_cfg.rules is not None else settings.rules


def resolve_stacks(settings: "Settings", repo_cfg: RepoConfig) -> StacksConfig:
    return repo_cfg.stacks if repo_cfg.stacks is not None else settings.stacks


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
            ingress=IngressConfig(**raw.get("ingress", {})),
            poller=PollerConfig(**raw.get("poller", {})),
            rules=RulesConfig(**raw.get("rules", {})),
            stacks=StacksConfig(**raw.get("stacks", {})),
            bot_handle=raw.get("bot_handle", ""),
        )
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}") from e
