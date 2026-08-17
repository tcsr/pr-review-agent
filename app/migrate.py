from __future__ import annotations

import os

from alembic import command
from alembic.config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_migrations(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
