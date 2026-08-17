from app.config import (load_settings, RulesConfig, StacksConfig, GateConfig,
                        RepoConfig, Settings, LLMConfig, StoreConfig,
                        resolve_rules, resolve_stacks)
from app.models import Platform


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_loads_rules_and_stacks(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
rules:
  gates:
    require_linked_issue: {enabled: true, severity: warn}
    title_regex: {severity: block, pattern: '^(feat|fix): '}
  review_criteria:
    - "No debug prints."
stacks:
  auto_detect: true
  packs: {angular: false}
repos: []
""")
    s = load_settings(path, env={})
    assert s.rules.gates["title_regex"].severity == "block"
    assert s.rules.gates["title_regex"].pattern == "^(feat|fix): "
    assert s.rules.review_criteria == ["No debug prints."]
    assert s.stacks.packs["angular"] is False


def test_resolve_prefers_repo_over_global():
    global_rules = RulesConfig(review_criteria=["global"])
    repo_rules = RulesConfig(review_criteria=["repo"])
    s = Settings(llm=LLMConfig(), store=StoreConfig(), defaults_tasks=["code_review"],
                 repos=[], rules=global_rules)
    rc_with = RepoConfig(platform=Platform.github, full_name="o/r", token="t", rules=repo_rules)
    rc_without = RepoConfig(platform=Platform.github, full_name="o/r", token="t")
    assert resolve_rules(s, rc_with).review_criteria == ["repo"]
    assert resolve_rules(s, rc_without).review_criteria == ["global"]


def test_resolve_stacks_default_global():
    s = Settings(llm=LLMConfig(), store=StoreConfig(), defaults_tasks=["code_review"], repos=[])
    rc = RepoConfig(platform=Platform.github, full_name="o/r", token="t")
    assert resolve_stacks(s, rc).auto_detect is True
