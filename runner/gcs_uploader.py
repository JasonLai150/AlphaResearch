"""Ship a sub-agent's artifact dir to GCS, then record ArtifactRefs in Redis.

Artifact ids are content-addressed by (session, job, filename) — SEV-10 — so a
reconcile retry that re-uploads the same blob re-derives the SAME id, making the
JSON.SET + SADD idempotent instead of minting a duplicate ref each pass.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from infra import store
from infra.config import settings
from infra.schemas import ArtifactRef


def _kind_for(p: Path) -> str:
    suffix = p.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".svg", ".gif"):
        return "plot"
    if suffix in (".pt", ".ckpt", ".bin", ".safetensors"):
        return "checkpoint"
    if suffix in (".log", ".txt"):
        return "log"
    return "other"


async def upload_artifacts(session_id: str, job_id: str, local_dir: Path) -> list[ArtifactRef]:
    if not local_dir.exists():
        return []
    client = store._gcs_client()  # shared credential path (uses the injected SA key)
    bucket_name = settings.gcs_bucket or "alpha-test"
    bucket = client.bucket(bucket_name)
    r = store.get_redis()
    refs: list[ArtifactRef] = []
    for p in sorted(local_dir.iterdir()):
        if not p.is_file():
            continue
        data = p.read_bytes()
        path_in_bucket = f"{session_id}/{job_id}/{p.name}"
        blob = bucket.blob(path_in_bucket)
        content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        blob.upload_from_string(data, content_type=content_type)
        aid = store.deterministic_artifact_id(session_id, job_id, p.name)  # SEV-10
        ref = ArtifactRef(
            id=aid, job_id=job_id, kind=_kind_for(p),
            url=f"gs://{bucket_name}/{path_in_bucket}", caption=p.name, bytes=len(data),
        )
        await r.json().set(f"artifact:{aid}", "$", ref.model_dump())
        await store.link_artifact_to_job(job_id, aid)
        refs.append(ref)
    return refs
