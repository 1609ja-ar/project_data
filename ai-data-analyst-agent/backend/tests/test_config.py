"""Settings parsing: the values .env.example ships with must load."""
from app.core.config import Settings


def test_empty_cookie_secure_means_unset(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "")
    s = Settings(_env_file=None)
    assert s.cookie_secure is None


def test_cookie_secure_explicit(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    assert Settings(_env_file=None).cookie_secure is True
