"""Shared test fixtures.

Two rules that the whole suite depends on:

1. **Mutate the `settings` singleton in place** (never reassign
   ``config.settings = Settings()``). Every module did ``from infra.config import
   settings``, binding the *object*; reassigning the module attribute would not
   reach those bound names, but ``monkeypatch.setattr(settings, ...)`` does.
2. **`fake_redis` swaps `store._redis`** for a ``fakeredis.aioredis`` instance, so
   every ``store.get_redis()`` call across all modules shares one in-memory Redis
   (with RedisJSON + Lua support via the ``fakeredis[json,lua]`` extra).
"""

from __future__ import annotations

import os

# Tests use fakeredis + monkeypatched settings — never the developer's real .env Redis.
# Force a valid-scheme URL BEFORE infra.config's module-level Settings() runs, so a
# missing/malformed local .env ALPHA_REDIS_URL can't break collection. The scheme
# validator itself is tested explicitly in tests/test_config_redis_url.py.
os.environ["ALPHA_REDIS_URL"] = "redis://localhost:6379/0"

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    from infra.config import settings

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(settings, "internal_token", "test-token")
    monkeypatch.setattr(settings, "internal_runner_url", "http://runner.test")
    monkeypatch.setattr(settings, "volume_root", str(tmp_path / "volumes"))
    # Force the local artifact path in store.put_artifact (no real GCS in CI) and
    # keep written bytes inside the test's tmp dir.
    monkeypatch.setattr(settings, "gcs_bucket", None)
    monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path / "artifacts"))
    yield


@pytest.fixture
async def fake_redis(monkeypatch):
    fr = fakeredis.aioredis.FakeRedis(decode_responses=True)
    from infra import store

    monkeypatch.setattr(store, "_redis", fr)
    yield fr
    await fr.aclose()
    monkeypatch.setattr(store, "_redis", None)
