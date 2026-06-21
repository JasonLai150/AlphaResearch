"""End-to-end smoke: POST /sessions -> session_loop spawns main agent -> main agent
POSTs /internal/dispatch -> dispatch_loop spawns sub-agent -> sub-agent writes its
result + artifact into the volume -> reconcile_loop finalizes + uploads -> GET
/sessions/{sid}/full shows the whole tree.

Only the cloud spawns/polls and the GCS network call are mocked; the API, the
internal router, the runner loops, the store, and the artifact path all run for real
(fakeredis). This is the full Cloud-Run-main-agent + Modal-sub-agent arch."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from infra import store
from runner import loops, modal_client

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client(fake_redis):
    from orchestrator import api as api_mod
    async with AsyncClient(transport=ASGITransport(app=api_mod.app), base_url="http://t") as c:
        yield c


def _mock_client():
    client = MagicMock()
    bucket = MagicMock()
    client.bucket.return_value = bucket
    bucket.blob.return_value = MagicMock()
    return client


async def test_end_to_end_session_dispatch_reconcile(client, fake_redis):
    # 1. Create a session.
    r = await client.post("/sessions", json={"user_id": "u_1", "goal": "explore RL"})
    sid = r.json()["session_id"]
    root_id = r.json()["root_job_id"]

    # 2. session_loop spawns the main-agent Cloud Run Job.
    with patch("runner.loops.spawn_main_agent_job", AsyncMock(return_value="exec_root")):
        await loops._consume_sessions_once()
    root = await store.get_job(root_id)
    assert root.sandbox_id == "exec_root" and root.status.value == "running"
    assert root.backend == "cloud_run_job"

    # 3. The main agent dispatches a sub-agent via the internal API (authed with the
    #    per-session token the runner would have injected at spawn).
    tok = await store.get_session_token(sid)
    dr = await client.post(
        "/internal/dispatch",
        json={"job_id": "j_c", "parent_job_id": root_id, "session_id": sid, "depth": 1,
              "kind": "agent", "plan": {"id": "p"}, "idea_id": "idea_1",
              "strategy": "exploration: noisy-net"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert dr.status_code == 202
    assert (await store.get_job("j_c")).parent_job_id == root_id

    # 4. dispatch_loop spawns the sub-agent Modal Function.
    with patch("runner.loops.spawn_sub_agent", AsyncMock(return_value="sb_c")), \
         patch("runner.loops.write_dispatch_record", MagicMock()):
        await loops._consume_dispatches_once()
    assert (await store.get_job("j_c")).sandbox_id == "sb_c"

    # 5. Simulate the sub-agent finishing: result.json + .done sentinel + an artifact
    #    land in the shared volume.
    result_path, _ = modal_client.results_for(sid, "j_c")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({
        "job_id": "j_c", "status": "done", "summary": "ppo+icm hit 0.82",
        "metrics": {"score": 0.82},
    }))
    modal_client.result_done_sentinel(sid, "j_c").write_text("done")
    art = modal_client.artifacts_dir(sid, "j_c")
    art.mkdir(parents=True, exist_ok=True)
    (art / "loss.png").write_bytes(b"PNGSTUB")

    # 6. reconcile: child done (Modal), root still running (Cloud Run). Real
    #    upload_artifacts runs against a mocked GCS client.
    async def poll_modal(sb):
        return "done" if sb == "sb_c" else "running"

    with patch("runner.loops.poll_modal_call", AsyncMock(side_effect=poll_modal)), \
         patch("runner.loops.poll_cloud_run_exec", AsyncMock(return_value="running")), \
         patch("runner.loops.reload_volume", AsyncMock()), \
         patch("runner.loops.delete_session_volume", AsyncMock()), \
         patch("infra.store._gcs_client", _mock_client):
        await loops._reconcile_once()

    assert (await store.get_job("j_c")).status.value == "done"
    run = await store.get_run("j_c")
    assert run is not None and run.summary == "ppo+icm hit 0.82" and run.metrics["score"] == 0.82

    # 7. The full session payload reflects the whole tree + the uploaded artifact.
    full = (await client.get(f"/sessions/{sid}/full")).json()
    assert {j["id"] for j in full["jobs"]} == {root_id, "j_c"}
    assert any(rn["job_id"] == "j_c" and rn["summary"] == "ppo+icm hit 0.82"
               for rn in full["runs"])
    assert full["tree"][root_id] == ["j_c"]
    assert any(a["job_id"] == "j_c" and a["kind"] == "plot" for a in full["artifacts"])

    # 8. The main agent can poll its children over the internal API.
    children = (await client.get(f"/internal/children/{root_id}",
                                 headers={"Authorization": f"Bearer {tok}"})).json()
    assert len(children) == 1 and children[0]["job_id"] == "j_c" and children[0]["done"] is True
