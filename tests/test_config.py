import pytest
from app.config import load_settings
from app.models import Platform


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_load_valid_config(tmp_path):
    path = _write(tmp_path, """
llm:
  provider: fake
  model: fake
store:
  url: 'sqlite:///:memory:'
defaults:
  tasks: [code_review, summarize]
repos:
  - platform: github
    full_name: o/r
    token: ${GH_TOKEN}
    tasks: null
""")
    s = load_settings(path, env={"GH_TOKEN": "secret"})
    assert s.repos[0].platform == Platform.github
    assert s.repos[0].token == "secret"
    assert s.defaults_tasks == ["code_review", "summarize"]


def test_missing_env_var_raises(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos:
  - {platform: github, full_name: o/r, token: '${MISSING}'}
""")
    with pytest.raises(ValueError, match="MISSING"):
        load_settings(path, env={})


def test_unknown_platform_raises(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos:
  - {platform: svn, full_name: o/r, token: t}
""")
    with pytest.raises(ValueError):
        load_settings(path, env={})


def test_llm_config_api_key_and_base_url(tmp_path):
    path = _write(tmp_path, """
llm:
  provider: openai
  model: gpt-x
  api_key: ${OAI}
  base_url: http://localhost:11434/v1
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos: []
""")
    s = load_settings(path, env={"OAI": "sk-test"})
    assert s.llm.api_key == "sk-test"
    assert s.llm.base_url == "http://localhost:11434/v1"
