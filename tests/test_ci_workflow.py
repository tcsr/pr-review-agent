import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_ci_runs_pytest():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml")) as f:
        data = yaml.safe_load(f)
    # triggers on push and pull_request
    on = data.get("on") or data.get(True)  # yaml parses bare `on:` as True
    assert on is not None
    text = yaml.dump(data)
    assert "pytest" in text
    assert "pip install" in text
