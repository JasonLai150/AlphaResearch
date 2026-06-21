"""Prebaked trainer (agent/sub-agent/scripts/train_ppo.py).

Pure-function tests are CI-safe (numpy only). The end-to-end smoke is guarded on
torch/gymnasium/minigrid (installed only in the Modal sub-agent image, not the dev extra),
so it runs locally if those are present and skips cleanly in CI.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "agent" / "sub-agent" / "scripts")
)
import train_ppo  # noqa: E402


def test_parse_intervention_coerces_types():
    out = train_ppo.parse_intervention("ent_coef=0.05, num_steps=64, norm_adv=false")
    assert out == {"ent_coef": 0.05, "num_steps": 64, "norm_adv": False}
    assert isinstance(out["num_steps"], int)
    assert out["norm_adv"] is False


def test_parse_intervention_empty_is_noop():
    assert train_ppo.parse_intervention("") == {}


def test_parse_intervention_rejects_unknown_knob():
    with pytest.raises(SystemExit):
        train_ppo.parse_intervention("not_a_knob=1")


def test_parse_intervention_rejects_malformed():
    with pytest.raises(SystemExit):
        train_ppo.parse_intervention("ent_coef")  # no '='


def test_encode_obs_minigrid_dict():
    obs = {"image": np.zeros((4, 7, 7, 3), dtype=np.uint8),
           "direction": np.array([0, 1, 2, 3])}
    enc = train_ppo.encode_obs(obs, 4)
    assert enc.shape == (4, 7 * 7 * 3 + 4)   # flat image + one-hot direction
    assert enc.dtype == np.float32


def test_encode_obs_flat_box_passthrough():
    obs = np.ones((3, 5), dtype=np.float32)
    assert train_ppo.encode_obs(obs, 3).shape == (3, 5)


def test_tunable_matches_schema_knobs():
    # train_ppo TUNABLE must equal the schema's TUNABLE_KNOBS (single source of truth).
    sys.path.insert(
        0, str(Path(__file__).resolve().parent.parent / "agent" / "main-agent" / "scripts"))
    from schemas import TUNABLE_KNOBS
    assert set(train_ppo.TUNABLE) == set(TUNABLE_KNOBS)


_MISSING = [m for m in ("torch", "gymnasium", "minigrid")
            if importlib.util.find_spec(m) is None]


@pytest.mark.skipif(bool(_MISSING), reason=f"train deps missing (Modal image only): {_MISSING}")
def test_train_smoke_writes_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHA_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("ALPHA_DISPATCH_DIR", str(tmp_path / ".dispatched"))
    monkeypatch.setenv("ALPHA_JOB_ID", "j_smoke")
    monkeypatch.setattr(sys, "argv", [
        "train_ppo.py", "--env", "MiniGrid-Empty-5x5-v0", "--total-steps", "512",
        "--num-envs", "2", "--intervention", "ent_coef=0.05"])
    assert train_ppo.main() == 0
    res = json.loads((tmp_path / "result.json").read_text())
    assert res["status"] == "done"
    assert "delta_vs_baseline" in res["metrics"]
    art = tmp_path / ".dispatched" / "artifacts" / "j_smoke"
    assert (art / "training_curves.png").exists()
    assert (art / "metrics.json").exists()
