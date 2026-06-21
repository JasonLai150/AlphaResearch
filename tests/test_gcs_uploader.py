"""GCS uploader — storage client mocked. SEV-10: deterministic, idempotent ids."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from infra import store
from runner.gcs_uploader import upload_artifacts

pytestmark = pytest.mark.asyncio


def _mock_storage():
    mock_storage = MagicMock()
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    mock_storage.Client.return_value = client
    client.bucket.return_value = bucket
    bucket.blob.return_value = blob
    return mock_storage


async def test_uploads_each_file_with_deterministic_ids(fake_redis, tmp_path):
    art = tmp_path / "artifacts" / "j_1"
    art.mkdir(parents=True)
    (art / "loss.png").write_bytes(b"\x89PNGfake")
    (art / "metrics.json").write_bytes(b'{"r": 0.5}')

    with patch("runner.gcs_uploader.storage", _mock_storage()):
        refs = await upload_artifacts("s_a", "j_1", art)

    assert len(refs) == 2
    for ref in refs:
        assert ref.url.startswith("gs://alpha-test/s_a/j_1/")
        assert ref.bytes > 0
    assert {r.id for r in refs} == {
        store.deterministic_artifact_id("s_a", "j_1", "loss.png"),
        store.deterministic_artifact_id("s_a", "j_1", "metrics.json"),
    }
    assert sorted(r.kind for r in refs) == ["other", "plot"]


async def test_idempotent_reupload(fake_redis, tmp_path):
    art = tmp_path / "artifacts" / "j_1"
    art.mkdir(parents=True)
    (art / "loss.png").write_bytes(b"PNG")
    with patch("runner.gcs_uploader.storage", _mock_storage()):
        await upload_artifacts("s_a", "j_1", art)
        await upload_artifacts("s_a", "j_1", art)  # reconcile retry
    listed = await store.list_artifacts_for("j_1")
    assert len(listed) == 1  # SEV-10: same id, no duplicate ref


async def test_no_artifacts_returns_empty(fake_redis, tmp_path):
    refs = await upload_artifacts("s_a", "j_1", tmp_path / "missing")
    assert refs == []
