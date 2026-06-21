"""ALPHA_REDIS_URL scheme validation (infra/config.py).

Regression guard for the incident where the alpha-redis-url secret was saved as a
verbatim "ALPHA_REDIS_URL=redis://..." env line (scheme buried mid-string), so
redis.from_url() raised inside the swallowed leadership_loop exception and the runner
silently never became leader for ~40 min. Settings now fails LOUDLY at load instead.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from infra.config import Settings


@pytest.mark.parametrize(
    "bad",
    [
        "localhost:6379",                      # bare host:port (the Redis Cloud dashboard form)
        "default:pw@host.example:6379",        # user:pass@host:port, no scheme
        "ALPHA_REDIS_URL=redis://host:6379",   # the exact mangled-secret class from the incident
        "http://host:6379",                    # wrong scheme entirely
        "",                                    # empty
    ],
)
def test_rejects_value_without_valid_scheme(monkeypatch, bad):
    monkeypatch.setenv("ALPHA_REDIS_URL", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "good",
    [
        "redis://localhost:6379/0",
        "rediss://default:pw@host.example:6379",
        "unix:///var/run/redis.sock",
    ],
)
def test_accepts_valid_schemes(monkeypatch, good):
    monkeypatch.setenv("ALPHA_REDIS_URL", good)
    assert Settings(_env_file=None).redis_url == good


def test_strips_surrounding_whitespace(monkeypatch):
    # A leading newline/space before the scheme also trips redis.from_url; strip it.
    monkeypatch.setenv("ALPHA_REDIS_URL", "  redis://h:6379  ")
    assert Settings(_env_file=None).redis_url == "redis://h:6379"
