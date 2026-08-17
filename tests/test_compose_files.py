import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name)) as f:
        return f.read()


def test_dockerfile_runs_the_app():
    df = _read("Dockerfile")
    assert "python" in df.lower()
    assert "app.main" in df  # entrypoint runs the module


def test_dockerignore_excludes_caches():
    di = _read(".dockerignore")
    assert "__pycache__" in di
    assert ".git" in di


def test_compose_defines_agent_service_and_volume():
    data = yaml.safe_load(_read("docker-compose.yml"))
    assert "services" in data
    assert "agent" in data["services"]
    agent = data["services"]["agent"]
    assert "8000" in str(agent.get("ports", []))
    # a volume is mounted for the sqlite data dir
    assert any("/data" in str(v) for v in agent.get("volumes", []))


def test_compose_has_postgres_profile():
    data = yaml.safe_load(_read("docker-compose.yml"))
    assert "postgres" in data["services"]
    assert "profiles" in data["services"]["postgres"]
