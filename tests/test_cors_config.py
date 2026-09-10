"""Tests for CORS allowlist configuration (no wildcard in production defaults)."""

from fastapi.middleware.cors import CORSMiddleware

from backend.config import AppSettings, settings


def _cors_middleware_kwargs() -> dict:
    from backend.main import app

    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return middleware.kwargs
    raise AssertionError("CORSMiddleware not registered")


def test_cors_origin_list_parses_comma_separated_values():
    custom = AppSettings(cors_origins="https://a.example, https://b.example ,")
    assert custom.cors_origin_list == ["https://a.example", "https://b.example"]


def test_cors_origins_are_not_wildcard_by_default():
    default = AppSettings()
    assert "*" not in default.cors_origin_list
    assert "http://localhost:5173" in default.cors_origin_list


def test_app_cors_middleware_uses_allowlist():
    kwargs = _cors_middleware_kwargs()
    assert kwargs["allow_origins"] == settings.cors_origin_list
    assert "*" not in kwargs["allow_origins"]
    assert kwargs["allow_credentials"] is True


def test_wildcard_origins_disable_credentials():
    from backend.main import _allow_all_origins

    assert _allow_all_origins is False
