import pytest
from app.config import (validate_ui_settings, Settings, LLMConfig, StoreConfig, UIConfig)


def _s(**ui):
    return Settings(llm=LLMConfig(), store=StoreConfig(), defaults_tasks=["code_review"],
                    repos=[], ui=UIConfig(**ui))


def test_default_secret_rejected():
    with pytest.raises(ValueError):
        validate_ui_settings(_s(enabled=True, admin_user="a", admin_password_hash="h"))
        # session_secret defaults to "change-me"


def test_missing_admin_creds_rejected():
    with pytest.raises(ValueError):
        validate_ui_settings(_s(enabled=True, session_secret="rnd"))


def test_good_config_passes():
    validate_ui_settings(_s(enabled=True, session_secret="rnd", admin_user="a", admin_password_hash="h"))


def test_disabled_ui_skips_validation():
    validate_ui_settings(_s(enabled=False))  # no raise even with default secret
